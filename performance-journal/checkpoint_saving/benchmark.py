#!/usr/bin/env python3
"""
Checkpoint Writing Benchmark using Hugging Face Transformers
Measures performance of model checkpoint writing operations with optional usrbio acceleration.
"""

import os
import sys
import time
import shutil
import psutil
import argparse
from pathlib import Path
from typing import Dict, List, Tuple, Optional
import json
import torch
from transformers import (
    AutoModel, 
    AutoTokenizer, 
    AutoConfig,
    TrainingArguments,
    Trainer
)
import numpy as np
import tempfile
import io

# Configure loguru for nice structured logging
from loguru import logger

# Remove default handler and add custom one with nice formatting
logger.remove()
logger.add(
    sys.stderr,
    format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{function}</cyan> | <level>{message}</level>",
    level="INFO",  # Set to INFO for main output, can be changed to DEBUG for verbose
    colorize=True
)

# Add common directory to path for usrbio utilities
sys.path.append(str(Path(__file__).parent.parent / "common"))

# Import our comprehensive usrbio utilities
from usrbio_utils import (
    UsrbioDirectWriter,
    FileWriteResult,
    usrbio_save_state_dict,
    usrbio_save_pretrained,
    usrbio_save_checkpoint,
    USRBIO_AVAILABLE,
    TORCH_AVAILABLE
)

'''
# Example usage commands:

# Basic benchmark with local storage
python benchmark.py \
    --model "distilbert-base-uncased" \
    --cache-dir "/ssd/hf" \
    --checkpoint-dir "/ssd/checkpoints" \
    --iterations 3

# With usrbio acceleration on distributed filesystem
se python benchmark.py \
    --model "deepseek-ai/DeepSeek-R1-Distill-Qwen-1.5B" \
    --cache-dir "/3fs/stage/fuse/hf" \
    --checkpoint-dir "/3fs/stage/fuse/checkpoints" \
    --use-usrbio \
    --hf3fs-mount-point "/3fs/stage" \
    --usrbio-block-size $((1 << 25)) \
    --usrbio-priority 0 \
    --drop-caches \
    --iterations 1 \
    --runs 1

# Comprehensive benchmark with all methods
python benchmark.py \
    --model "bert-base-uncased" \
    --cache-dir "/3fs/stage/fuse/hf" \
    --checkpoint-dir "/3fs/stage/fuse/checkpoints" \
    --use-usrbio \
    --comprehensive-benchmark \
    --use-safetensors \
    --iterations 3 \
    --runs 5

# USRBIO-only testing
python benchmark.py \
    --model "deepseek-ai/DeepSeek-R1-Distill-Qwen-7B" \
    --cache-dir "/3fs/stage/fuse/hf" \
    --checkpoint-dir "/3fs/stage/fuse/checkpoints" \
    --use-usrbio \
    --usrbio-only \
    --usrbio-block-size $((1 << 30)) \
    --runs 3

# Compare different models
python benchmark.py \
    --models \
    "distilbert-base-uncased" \
    "bert-base-uncased" \
    "deepseek-ai/DeepSeek-R1-Distill-Qwen-1.5B" \
    --cache-dir "/ssd/hf" \
    --checkpoint-dir "/ssd/checkpoints" \
    --iterations 2 \
    --output model_comparison_results.json
'''

# Global reference to benchmark instance
_benchmark_instance = None


class CheckpointWritingBenchmark:
    """Benchmark for measuring checkpoint writing performance."""
    
    def __init__(self, 
                 cache_dir: str = "./cache",
                 checkpoint_dir: str = "./checkpoints",
                 use_usrbio: bool = False,
                 hf3fs_mount_point: Optional[str] = None,
                 usrbio_block_size: int = 1024*1024,  # 1MB default
                 usrbio_priority: int = 0,
                 drop_caches: bool = False,
                 max_concurrent: int = 8):
        """
        Initialize the benchmark.
        
        Args:
            cache_dir: Directory for caching downloaded models
            checkpoint_dir: Directory for writing checkpoints
            use_usrbio: Enable usrbio for distributed filesystem acceleration
            hf3fs_mount_point: Mount point for hf3fs (auto-detected if None)
            usrbio_block_size: Block size for usrbio operations
            usrbio_priority: I/O priority (-1=HIGH, 0=NORMAL, 1=LOW)
            drop_caches: Drop system caches before operations
            max_concurrent: Maximum concurrent file operations
        """
        self.cache_dir = Path(cache_dir)
        self.checkpoint_dir = Path(checkpoint_dir)
        self.use_usrbio = use_usrbio and USRBIO_AVAILABLE
        self.hf3fs_mount_point = hf3fs_mount_point
        self.usrbio_block_size = usrbio_block_size
        self.usrbio_priority = usrbio_priority
        self.drop_caches = drop_caches
        self.max_concurrent = max_concurrent
        self.results = []
        self.usrbio_stats = []
        
        # Create directories
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)
        
        if self.use_usrbio:
            if not USRBIO_AVAILABLE:
                logger.warning("⚠️  USRBIO requested but not available - falling back to standard saving")
                self.use_usrbio = False
            else:
                if not self.hf3fs_mount_point:
                    from usrbio_utils import extract_mount_point
                    self.hf3fs_mount_point = extract_mount_point(str(checkpoint_dir))
                logger.info(f"🚀 USRBIO enabled: mount={self.hf3fs_mount_point}, block_size={usrbio_block_size}, priority={usrbio_priority}")
        
        if self.drop_caches:
            logger.info("💧 CACHE DROPPING enabled - will drop system caches before each operation")
            self._test_cache_drop_permissions()
    
    def _test_cache_drop_permissions(self):
        """Test if we have permissions to drop caches."""
        try:
            with open('/proc/sys/vm/drop_caches', 'r') as f:
                current_value = f.read().strip()
            logger.info(f"💧 Cache drop permissions: OK (current value: {current_value})")
        except PermissionError:
            logger.warning("⚠️  WARNING: No permission to drop caches. Run with sudo or disable --drop-caches")
        except Exception as e:
            logger.warning(f"⚠️  WARNING: Cannot access cache drop interface: {e}")
    
    def _drop_system_caches(self):
        """Drop system caches to ensure fresh I/O operations."""
        if not self.drop_caches:
            return
            
        try:
            logger.debug("💧 Dropping system caches...")
            os.system('sync')
            with open('/proc/sys/vm/drop_caches', 'w') as f:
                f.write('3\n')
            logger.debug("💧 System caches dropped successfully")
        except PermissionError:
            logger.error("⚠️  ERROR: No permission to drop caches. Run with sudo or disable --drop-caches")
        except Exception as e:
            logger.error(f"⚠️  ERROR: Failed to drop caches: {e}")
    
    def setup_model(self, model_name: str) -> Tuple[Optional[object], Optional[object], Optional[object]]:
        """Load model, tokenizer, and config with caching."""
        logger.info(f"Loading model {model_name} with cache_dir: {self.cache_dir}")
        
        start_time = time.perf_counter()
        
        try:
            # Load with cache directory
            config = AutoConfig.from_pretrained(
                model_name, 
                cache_dir=self.cache_dir
            )
            
            tokenizer = AutoTokenizer.from_pretrained(
                model_name,
                cache_dir=self.cache_dir
            )
            
            model = AutoModel.from_pretrained(
                model_name,
                cache_dir=self.cache_dir,
                config=config,
                torch_dtype=torch.float16 if torch.cuda.is_available() else torch.float32
            )
            
            load_time = time.perf_counter() - start_time
            logger.success(f"✅ Model loaded in {load_time:.2f} seconds")
            
            return model, tokenizer, config
            
        except Exception as e:
            logger.error(f"❌ Failed to load model {model_name}: {e}")
            return None, None, None

    def get_directory_size(self, directory: Path) -> int:
        """Get total size of directory in bytes."""
        total_size = 0
        for dirpath, dirnames, filenames in os.walk(directory):
            for filename in filenames:
                filepath = os.path.join(dirpath, filename)
                if os.path.exists(filepath):
                    total_size += os.path.getsize(filepath)
        return total_size
    
    def measure_system_resources(self) -> Dict[str, float]:
        """Measure current system resource usage."""
        process = psutil.Process()
        return {
            "cpu_percent": psutil.cpu_percent(interval=0.1),
            "memory_mb": process.memory_info().rss / 1024 / 1024,
            "disk_io_read_mb": psutil.disk_io_counters().read_bytes / 1024 / 1024,
            "disk_io_write_mb": psutil.disk_io_counters().write_bytes / 1024 / 1024,
        }

    def benchmark_manual_save_pretrained(self, model, tokenizer, checkpoint_name: str) -> Dict[str, float]:
        """Benchmark manual checkpoint saving using save_pretrained."""
        checkpoint_path = self.checkpoint_dir / checkpoint_name
        
        # Drop caches for fresh I/O
        self._drop_system_caches()
        
        # Clean up previous checkpoint
        if checkpoint_path.exists():
            shutil.rmtree(checkpoint_path)
        checkpoint_path.mkdir(parents=True)
        
        # Measure before
        resources_before = self.measure_system_resources()
        start_time = time.perf_counter()
        
        # Save checkpoint
        if self.use_usrbio:
            logger.info(f"🚀 Using USRBIO-accelerated save_pretrained to {checkpoint_path}")
            usrbio_results = usrbio_save_pretrained(
                model=model,
                tokenizer=tokenizer,
                output_dir=str(checkpoint_path),
                hf3fs_mount_point=self.hf3fs_mount_point,
                priority=self.usrbio_priority,
                use_safetensors=False
            )
            
            if usrbio_results:
                logger.success("✅ USRBIO save_pretrained completed successfully")
            else:
                logger.warning("📁 USRBIO failed, falling back to standard save_pretrained")
                model.save_pretrained(checkpoint_path)
                if tokenizer:
                    tokenizer.save_pretrained(checkpoint_path)
        else:
            logger.info(f"📁 Using standard save_pretrained to {checkpoint_path}")
            model.save_pretrained(checkpoint_path)
            if tokenizer:
                tokenizer.save_pretrained(checkpoint_path)
        
        # Measure after
        end_time = time.perf_counter()
        resources_after = self.measure_system_resources()
        
        checkpoint_size = self.get_directory_size(checkpoint_path)
        
        result = {
            "method": "save_pretrained",
            "checkpoint_name": checkpoint_name,
            "write_time_seconds": end_time - start_time,
            "checkpoint_size_mb": checkpoint_size / 1024 / 1024,
            "cpu_usage_percent": resources_after["cpu_percent"] - resources_before["cpu_percent"],
            "memory_usage_mb": resources_after["memory_mb"] - resources_before["memory_mb"],
            "disk_write_mb": resources_after["disk_io_write_mb"] - resources_before["disk_io_write_mb"],
            "usrbio_enabled": self.use_usrbio,
        }
        
        if self.use_usrbio and usrbio_results:
            successful_writes = [r for r in usrbio_results.values() if r.success]
            if successful_writes:
                result["usrbio_write_time"] = sum(r.write_time for r in successful_writes)
                result["usrbio_throughput_gbps"] = sum(r.throughput_gbps for r in successful_writes) / len(successful_writes)
                result["usrbio_files"] = len(successful_writes)
        
        return result
    
    def benchmark_torch_save(self, model, config, checkpoint_name: str) -> Dict[str, float]:
        """Benchmark checkpoint saving using torch.save."""
        checkpoint_path = self.checkpoint_dir / f"{checkpoint_name}.pt"
        
        # Drop caches for fresh I/O
        self._drop_system_caches()
        
        # Remove if exists
        if checkpoint_path.exists():
            checkpoint_path.unlink()
        
        # Measure before
        resources_before = self.measure_system_resources()
        start_time = time.perf_counter()
        
        # Save model state dict
        save_data = {
            'model_state_dict': model.state_dict(),
            'config': config.to_dict() if config else {},
        }
        
        if self.use_usrbio:
            logger.info(f"🚀 Using USRBIO-accelerated torch.save to {checkpoint_path}")
            
            usrbio_result = usrbio_save_state_dict(
                state_dict=save_data,
                output_dir=str(checkpoint_path.parent),
                filename=checkpoint_path.name,
                hf3fs_mount_point=self.hf3fs_mount_point,
                priority=self.usrbio_priority,
                use_safetensors=False
            )
            
            if not usrbio_result or not usrbio_result.success:
                logger.warning("📁 USRBIO failed, falling back to standard torch.save")
                torch.save(save_data, checkpoint_path)
        else:
            logger.info(f"📁 Using standard torch.save to {checkpoint_path}")
            torch.save(save_data, checkpoint_path)
        
        # Measure after
        end_time = time.perf_counter()
        resources_after = self.measure_system_resources()
        
        checkpoint_size = checkpoint_path.stat().st_size
        
        result = {
            "method": "torch_save",
            "checkpoint_name": checkpoint_name,
            "write_time_seconds": end_time - start_time,
            "checkpoint_size_mb": checkpoint_size / 1024 / 1024,
            "cpu_usage_percent": resources_after["cpu_percent"] - resources_before["cpu_percent"],
            "memory_usage_mb": resources_after["memory_mb"] - resources_before["memory_mb"],
            "disk_write_mb": resources_after["disk_io_write_mb"] - resources_before["disk_io_write_mb"],
            "usrbio_enabled": self.use_usrbio,
        }
        
        if self.use_usrbio and usrbio_result and usrbio_result.success:
            result["usrbio_write_time"] = usrbio_result.write_time
            result["usrbio_throughput_gbps"] = usrbio_result.throughput_gbps
        
        return result
    
    def benchmark_trainer_save(self, model, checkpoint_name: str) -> Dict[str, float]:
        """Benchmark checkpoint saving using Hugging Face Trainer."""
        checkpoint_path = self.checkpoint_dir / f"trainer_{checkpoint_name}"
        
        # Drop caches for fresh I/O
        self._drop_system_caches()
        
        # Clean up previous checkpoint
        if checkpoint_path.exists():
            shutil.rmtree(checkpoint_path)
        
        # Create minimal training arguments
        training_args = TrainingArguments(
            output_dir=str(checkpoint_path),
            save_strategy="no",  # We'll save manually
            logging_dir=None,
        )
        
        # Create trainer
        trainer = Trainer(
            model=model,
            args=training_args,
        )
        
        # Measure before
        resources_before = self.measure_system_resources()
        start_time = time.perf_counter()
        
        # Save checkpoint using trainer
        logger.info(f"📁 Using trainer.save_model to {checkpoint_path}")
        trainer.save_model(checkpoint_path)
        
        # Measure after
        end_time = time.perf_counter()
        resources_after = self.measure_system_resources()
        
        checkpoint_size = self.get_directory_size(checkpoint_path)
        
        result = {
            "method": "trainer_save",
            "checkpoint_name": checkpoint_name,
            "write_time_seconds": end_time - start_time,
            "checkpoint_size_mb": checkpoint_size / 1024 / 1024,
            "cpu_usage_percent": resources_after["cpu_percent"] - resources_before["cpu_percent"],
            "memory_usage_mb": resources_after["memory_mb"] - resources_before["memory_mb"],
            "disk_write_mb": resources_after["disk_io_write_mb"] - resources_before["disk_io_write_mb"],
            "usrbio_enabled": False,  # Trainer doesn't use our USRBIO hooks
        }
        
        return result
    
    def benchmark_comprehensive_checkpoint(self, model, config, checkpoint_name: str) -> Dict[str, float]:
        """Benchmark comprehensive checkpoint saving using usrbio_save_checkpoint."""
        checkpoint_path = self.checkpoint_dir / f"comprehensive_{checkpoint_name}"
        
        # Drop caches for fresh I/O
        self._drop_system_caches()
        
        # Clean up previous checkpoint
        if checkpoint_path.exists():
            shutil.rmtree(checkpoint_path)
        
        # Measure before
        resources_before = self.measure_system_resources()
        start_time = time.perf_counter()
        
        # Create comprehensive checkpoint data
        logger.debug("🔧 Preparing comprehensive checkpoint data...")
        
        # Simulate optimizer and scheduler states (since we don't have real training)
        import torch.optim as optim
        dummy_optimizer = optim.AdamW(model.parameters(), lr=1e-4)
        dummy_scheduler = optim.lr_scheduler.StepLR(dummy_optimizer, step_size=1000, gamma=0.9)
        
        # Prepare comprehensive checkpoint data
        checkpoint_data = {
            'model_state_dict': model.state_dict(),
            'optimizer_state_dict': dummy_optimizer.state_dict(),
            'scheduler_state_dict': dummy_scheduler.state_dict(),
            'epoch': 10,
            'step': 1000,
            'best_metric': 0.85,
            'loss': 0.23,
            'learning_rate': 1e-4,
            'random_states': {
                'python': None,  # Would normally be random.getstate()
                'numpy': None,   # Would normally be np.random.get_state()
                'torch': torch.get_rng_state(),
                'torch_cuda': torch.cuda.get_rng_state_all() if torch.cuda.is_available() else None
            },
            'metadata': {
                'model_name': 'benchmark_model',
                'benchmark_version': '1.0',
                'batch_size': 32,
                'created_by': 'checkpoint_benchmark'
            }
        }
        
        # Save checkpoint using comprehensive method
        if self.use_usrbio:
            logger.info(f"🚀 Using comprehensive USRBIO checkpoint save to {checkpoint_path}")
            
            usrbio_result = usrbio_save_checkpoint(
                checkpoint_data=checkpoint_data,
                output_dir=str(checkpoint_path),
                checkpoint_name="checkpoint",
                hf3fs_mount_point=self.hf3fs_mount_point,
                priority=self.usrbio_priority,
                use_safetensors=True,
                compress=False
            )
            
            if not usrbio_result or not usrbio_result.success:
                logger.warning("📁 USRBIO failed, falling back to standard torch.save")
                checkpoint_path.mkdir(parents=True, exist_ok=True)
                checkpoint_file = checkpoint_path / "checkpoint.pt"
                torch.save(checkpoint_data, checkpoint_file)
        else:
            logger.info(f"📁 Using standard torch.save for comprehensive checkpoint to {checkpoint_path}")
            checkpoint_path.mkdir(parents=True, exist_ok=True)
            checkpoint_file = checkpoint_path / "checkpoint.pt"
            torch.save(checkpoint_data, checkpoint_file)
        
        # Measure after
        end_time = time.perf_counter()
        resources_after = self.measure_system_resources()
        
        checkpoint_size = self.get_directory_size(checkpoint_path)
        
        result = {
            "method": "comprehensive_checkpoint",
            "checkpoint_name": checkpoint_name,
            "write_time_seconds": end_time - start_time,
            "checkpoint_size_mb": checkpoint_size / 1024 / 1024,
            "cpu_usage_percent": resources_after["cpu_percent"] - resources_before["cpu_percent"],
            "memory_usage_mb": resources_after["memory_mb"] - resources_before["memory_mb"],
            "disk_write_mb": resources_after["disk_io_write_mb"] - resources_before["disk_io_write_mb"],
            "usrbio_enabled": self.use_usrbio,
            "checkpoint_components": len(checkpoint_data),
        }
        
        if self.use_usrbio and usrbio_result and usrbio_result.success:
            result["usrbio_write_time"] = usrbio_result.write_time
            result["usrbio_throughput_gbps"] = usrbio_result.throughput_gbps
            if hasattr(usrbio_result, 'checkpoint_summary'):
                result["checkpoint_summary"] = usrbio_result.checkpoint_summary
        
        return result
    
    def benchmark_single_model(self, model_name: str, num_runs: int = 3, methods: List[str] = None) -> List[Dict[str, float]]:
        """Benchmark a single model with specified methods."""
        logger.info(f"\n--- Benchmarking {model_name} ---")
        
        # Setup model
        model, tokenizer, config = self.setup_model(model_name)
        if model is None:
            logger.error(f"❌ Failed to setup model {model_name}")
            return []
        
        # Default methods to test
        if methods is None:
            methods = ["save_pretrained", "torch_save", "trainer_save", "comprehensive_checkpoint"]
            if self.use_usrbio:
                # Add USRBIO-specific methods
                methods.append("usrbio_save_pretrained")
        
        model_results = []
        
        for run in range(num_runs):
            logger.info(f"\n--- Run {run + 1}/{num_runs} for {model_name} ---")
            
            for method_name in methods:
                checkpoint_name = f"{model_name.replace('/', '--')}_{method_name}_run_{run}"
                logger.info(f"Testing {method_name}...")
                
                try:
                    if method_name == "save_pretrained":
                        result = self.benchmark_manual_save_pretrained(model, tokenizer, checkpoint_name)
                    elif method_name == "torch_save":
                        result = self.benchmark_torch_save(model, config, checkpoint_name)
                    elif method_name == "trainer_save":
                        result = self.benchmark_trainer_save(model, checkpoint_name)
                    elif method_name == "comprehensive_checkpoint":
                        result = self.benchmark_comprehensive_checkpoint(model, config, checkpoint_name)
                    elif method_name == "usrbio_save_pretrained" and self.use_usrbio:
                        # Use the dedicated USRBIO save_pretrained with safetensors
                        checkpoint_path = self.checkpoint_dir / f"usrbio_{checkpoint_name}"
                        if checkpoint_path.exists():
                            shutil.rmtree(checkpoint_path)
                        
                        self._drop_system_caches()
                        resources_before = self.measure_system_resources()
                        start_time = time.perf_counter()
                        
                        usrbio_results = usrbio_save_pretrained(
                            model=model,
                            tokenizer=tokenizer,
                            output_dir=str(checkpoint_path),
                            hf3fs_mount_point=self.hf3fs_mount_point,
                            priority=self.usrbio_priority,
                            use_safetensors=True
                        )
                        
                        end_time = time.perf_counter()
                        resources_after = self.measure_system_resources()
                        checkpoint_size = self.get_directory_size(checkpoint_path)
                        
                        result = {
                            "method": "usrbio_save_pretrained",
                            "checkpoint_name": checkpoint_name,
                            "write_time_seconds": end_time - start_time,
                            "checkpoint_size_mb": checkpoint_size / 1024 / 1024,
                            "cpu_usage_percent": resources_after["cpu_percent"] - resources_before["cpu_percent"],
                            "memory_usage_mb": resources_after["memory_mb"] - resources_before["memory_mb"],
                            "disk_write_mb": resources_after["disk_io_write_mb"] - resources_before["disk_io_write_mb"],
                            "usrbio_enabled": True,
                        }
                        
                        if usrbio_results:
                            successful_writes = [r for r in usrbio_results.values() if r.success]
                            if successful_writes:
                                result["usrbio_write_time"] = sum(r.write_time for r in successful_writes)
                                result["usrbio_throughput_gbps"] = sum(r.throughput_gbps for r in successful_writes) / len(successful_writes)
                                result["usrbio_files"] = len(successful_writes)
                    else:
                        logger.warning(f"⚠️  Skipping unsupported method: {method_name}")
                        continue
                    
                    result["model_name"] = model_name
                    result["run"] = run
                    model_results.append(result)
                    
                    logger.success(f"  ✅ {method_name}: {result['write_time_seconds']:.2f}s, "
                          f"Size: {result['checkpoint_size_mb']:.1f}MB")
                    
                except Exception as e:
                    logger.error(f"  ❌ Error in {method_name}: {e}")
        
        # Clean up model from memory
        del model, tokenizer, config
        torch.cuda.empty_cache() if torch.cuda.is_available() else None
        
        return model_results
    
    def benchmark_multiple_models(self, models: List[str], num_runs: int = 3, methods: List[str] = None) -> List[Dict[str, float]]:
        """Benchmark multiple models."""
        logger.info(f"Starting benchmark with {len(models)} models, {num_runs} runs each")
        logger.info(f"Cache directory: {self.cache_dir}")
        logger.info(f"Checkpoint directory: {self.checkpoint_dir}")
        logger.info(f"Device: {'CUDA' if torch.cuda.is_available() else 'CPU'}")
        
        if self.use_usrbio:
            logger.info(f"🚀 USRBIO ACCELERATION: Enabled")
            logger.debug(f"   Mount point: {self.hf3fs_mount_point}")
            logger.debug(f"   Block size: {self.usrbio_block_size}")
            logger.debug(f"   Priority: {self.usrbio_priority}")
        else:
            logger.info("📁 Using standard I/O operations")
        
        all_results = []
        
        for i, model_name in enumerate(models, 1):
            logger.info(f"\n{'='*60}")
            logger.info(f"MODEL {i}/{len(models)}: {model_name}")
            logger.info(f"{'='*60}")
            
            model_results = self.benchmark_single_model(model_name, num_runs, methods)
            all_results.extend(model_results)
            
            if model_results:
                # Show model summary
                avg_times = {}
                for method in set(r['method'] for r in model_results):
                    method_results = [r for r in model_results if r['method'] == method]
                    avg_time = sum(r['write_time_seconds'] for r in method_results) / len(method_results)
                    avg_times[method] = avg_time
                
                logger.info(f"\n📊 {model_name} Summary:")
                for method, avg_time in sorted(avg_times.items(), key=lambda x: x[1]):
                    logger.info(f"   {method}: {avg_time:.3f}s average")
        
        self.results = all_results
        return all_results
        
    def analyze_results(self, results: List[Dict[str, float]]) -> Dict[str, Dict]:
        """Analyze benchmark results and compute statistics."""
        analysis = {}
        
        # Group by method
        methods = {}
        for result in results:
            method = result["method"]
            if method not in methods:
                methods[method] = []
            methods[method].append(result)
        
        # Compute statistics for each method
        for method, method_results in methods.items():
            times = [r["write_time_seconds"] for r in method_results]
            sizes = [r["checkpoint_size_mb"] for r in method_results]
            
            analysis[method] = {
                "avg_time_seconds": np.mean(times),
                "std_time_seconds": np.std(times),
                "min_time_seconds": np.min(times),
                "max_time_seconds": np.max(times),
                "avg_size_mb": np.mean(sizes),
                "std_size_mb": np.std(sizes),
                "iterations": len(method_results),
                "models_tested": len(set(r.get("model_name", "unknown") for r in method_results))
            }
            
            # Add USRBIO-specific metrics if available
            usrbio_times = [r.get("usrbio_write_time", 0) for r in method_results if r.get("usrbio_write_time")]
            usrbio_throughputs = [r.get("usrbio_throughput_gbps", 0) for r in method_results if r.get("usrbio_throughput_gbps")]
            
            if usrbio_times:
                analysis[method]["usrbio_avg_time_seconds"] = np.mean(usrbio_times)
                analysis[method]["usrbio_avg_throughput_gbps"] = np.mean(usrbio_throughputs)
        
        return analysis
    
    def print_results(self, analysis: Dict[str, Dict]) -> None:
        """Print formatted benchmark results."""
        logger.info("\n" + "="*80)
        logger.info("CHECKPOINT WRITING BENCHMARK RESULTS")
        logger.info("="*80)
        logger.info(f"Cache Directory: {self.cache_dir}")
        logger.info(f"Checkpoint Directory: {self.checkpoint_dir}")
        
        if self.use_usrbio:
            logger.info(f"🚀 USRBIO: Enabled (mount={self.hf3fs_mount_point}, block_size={self.usrbio_block_size})")
        else:
            logger.info("📁 USRBIO: Disabled (standard I/O)")
        
        logger.info("")
        
        # Sort methods by average time
        sorted_methods = sorted(analysis.items(), key=lambda x: x[1]["avg_time_seconds"])
        
        for method, stats in sorted_methods:
            acceleration_info = ""
            if stats.get("usrbio_avg_throughput_gbps"):
                acceleration_info = f" (🚀 {stats['usrbio_avg_throughput_gbps']:.2f} GB/s)"
            
            logger.info(f"Method: {method}{acceleration_info}")
            logger.info(f"  Average Time: {stats['avg_time_seconds']:.3f} ± {stats['std_time_seconds']:.3f} seconds")
            logger.info(f"  Time Range: {stats['min_time_seconds']:.3f} - {stats['max_time_seconds']:.3f} seconds")
            logger.info(f"  Average Size: {stats['avg_size_mb']:.1f} ± {stats['std_size_mb']:.1f} MB")
            logger.info(f"  Iterations: {stats['iterations']} (across {stats['models_tested']} models)")
            logger.info("")
    
    def save_results(self, results: List[Dict], analysis: Dict, filename: str = "checkpoint_writing_results.json") -> None:
        """Save results to JSON file."""
        output_data = {
            "cache_dir": str(self.cache_dir),
            "checkpoint_dir": str(self.checkpoint_dir),
            "usrbio_enabled": self.use_usrbio,
            "usrbio_config": {
                "mount_point": self.hf3fs_mount_point,
                "block_size": self.usrbio_block_size,
                "priority": self.usrbio_priority,
            } if self.use_usrbio else None,
            "drop_caches": self.drop_caches,
            "raw_results": results,
            "analysis": analysis,
            "timestamp": time.time(),
        }
        
        output_path = self.checkpoint_dir / filename
        with open(output_path, 'w') as f:
            json.dump(output_data, f, indent=2)
        logger.success(f"Results saved to: {output_path}")
    
    def cleanup(self) -> None:
        """Clean up checkpoint directory."""
        if hasattr(self, '_cleanup_enabled') and self._cleanup_enabled:
            logger.info(f"🧹 Cleaning up checkpoint directory: {self.checkpoint_dir}")
            if self.checkpoint_dir.exists():
                shutil.rmtree(self.checkpoint_dir)
                self.checkpoint_dir.mkdir(parents=True, exist_ok=True)


def main():
    """Main function to run the benchmark."""
    parser = argparse.ArgumentParser(
        description="Checkpoint Writing Benchmark for Hugging Face Transformers"
    )
    
    # Basic options
    parser.add_argument("--cache-dir", default="./cache", 
                       help="Directory for model caching")
    parser.add_argument("--checkpoint-dir", default="./checkpoints", 
                       help="Directory for checkpoint writing")
    parser.add_argument("--model", type=str,
                       help="Single Hugging Face model name to benchmark")
    parser.add_argument("--models", nargs='+',
                       help="Multiple Hugging Face model names to benchmark")
    parser.add_argument("--runs", type=int, default=3,
                       help="Number of runs per model (default: 3)")
    parser.add_argument("--iterations", type=int, default=1,
                       help="Number of iterations per run (default: 1)")
    parser.add_argument("--output", type=str, default="checkpoint_writing_results.json",
                       help="Output file for results (default: checkpoint_writing_results.json)")
    
    # Method selection
    parser.add_argument("--methods", nargs='+', 
                       choices=["save_pretrained", "torch_save", "trainer_save", "comprehensive_checkpoint", "usrbio_save_pretrained"],
                       help="Specific methods to benchmark (default: all available)")
    parser.add_argument("--comprehensive-benchmark", action="store_true",
                       help="Run comprehensive benchmark with all methods")
    
    # USRBIO options
    parser.add_argument("--use-usrbio", action="store_true",
                       help="Enable usrbio for distributed filesystem acceleration")
    parser.add_argument("--hf3fs-mount-point", type=str,
                       help="hf3fs mount point (auto-detected if not specified)")
    parser.add_argument("--usrbio-block-size", type=int, default=1024*1024,
                       help="Block size for usrbio operations (default: 1MB)")
    parser.add_argument("--usrbio-priority", type=int, choices=[-1, 0, 1], default=0,
                       help="I/O priority: -1=HIGH, 0=NORMAL, 1=LOW (default: 0)")
    parser.add_argument("--max-concurrent", type=int, default=8,
                       help="Maximum concurrent file operations for usrbio (default: 8)")
    parser.add_argument("--usrbio-only", action="store_true",
                       help="Test only USRBIO methods (requires --use-usrbio)")
    
    # System options
    parser.add_argument("--drop-caches", action="store_true",
                       help="Drop system caches before each operation (requires sudo)")
    parser.add_argument("--use-safetensors", action="store_true",
                       help="Use safetensors format where applicable")
    
    # Utility options
    parser.add_argument("--cleanup", action="store_true",
                       help="Clean up checkpoints after benchmark")
    parser.add_argument("--save-results", action="store_true", default=True,
                       help="Save results to JSON file")
    parser.add_argument("--verbose", "-v", action="store_true",
                       help="Enable verbose debug logging")
    
    args = parser.parse_args()
    
    # Configure logging level based on verbose flag
    if args.verbose:
        logger.remove()
        logger.add(
            sys.stderr,
            format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{function}</cyan> | <level>{message}</level>",
            level="DEBUG",
            colorize=True
        )
        logger.debug("Debug logging enabled")
    
    # Validate arguments
    if args.usrbio_only and not args.use_usrbio:
        logger.error("❌ --usrbio-only requires --use-usrbio to be enabled")
        return 1
    
    if not args.model and not args.models:
        logger.error("❌ Must specify either --model or --models")
        return 1
    
    # Prepare models list
    if args.models:
        models = args.models
    else:
        models = [args.model]
    
    # Prepare methods list
    methods = args.methods
    if args.usrbio_only:
        methods = ["usrbio_save_pretrained", "comprehensive_checkpoint"]
    elif args.comprehensive_benchmark:
        methods = ["save_pretrained", "torch_save", "trainer_save", "comprehensive_checkpoint"]
        if args.use_usrbio:
            methods.append("usrbio_save_pretrained")
    
    logger.info("Checkpoint Writing Benchmark")
    logger.info("="*40)
    logger.info(f"Models: {models}")
    logger.info(f"Cache Directory: {args.cache_dir}")
    logger.info(f"Checkpoint Directory: {args.checkpoint_dir}")
    logger.info(f"Runs: {args.runs}")
    logger.info(f"Iterations: {args.iterations}")
    
    if args.use_usrbio:
        logger.info(f"🚀 USRBIO: Enabled")
        logger.info(f"  Mount Point: {args.hf3fs_mount_point or 'auto-detect'}")
        logger.info(f"  Block Size: {args.usrbio_block_size}")
        logger.info(f"  Priority: {args.usrbio_priority}")
        if args.use_safetensors:
            logger.info(f"  Format: Safetensors (when available)")
        if args.usrbio_only:
            logger.info(f"  Mode: USRBIO-only testing")
    else:
        logger.info("📁 USRBIO: Disabled")
    
    if methods:
        logger.info(f"Methods: {methods}")
    
    # Initialize benchmark
    benchmark = CheckpointWritingBenchmark(
        cache_dir=args.cache_dir,
        checkpoint_dir=args.checkpoint_dir,
        use_usrbio=args.use_usrbio,
        hf3fs_mount_point=args.hf3fs_mount_point,
        usrbio_block_size=args.usrbio_block_size,
        usrbio_priority=args.usrbio_priority,
        drop_caches=args.drop_caches,
        max_concurrent=args.max_concurrent
    )
    
    # Set cleanup flag
    benchmark._cleanup_enabled = args.cleanup
    
    # Set global reference
    global _benchmark_instance
    _benchmark_instance = benchmark
    
    try:
        # Run benchmarks for multiple iterations
        all_results = []
        for iteration in range(args.iterations):
            if args.iterations > 1:
                logger.info(f"\n{'='*60}")
                logger.info(f"ITERATION {iteration + 1}/{args.iterations}")
                logger.info(f"{'='*60}")
            
            results = benchmark.benchmark_multiple_models(models, args.runs, methods)
            
            # Add iteration info to results
            for result in results:
                result["iteration"] = iteration
            
            all_results.extend(results)
        
        # Analyze results
        analysis = benchmark.analyze_results(all_results)
        
        # Print results
        benchmark.print_results(analysis)
        
        # Save results
        if args.save_results:
            benchmark.save_results(all_results, analysis, args.output)
        
    except KeyboardInterrupt:
        logger.warning("⚠️  Benchmark interrupted by user")
        return 130
    except Exception as e:
        logger.error(f"❌ Benchmark failed: {e}")
        import traceback
        logger.debug(f"Traceback: {traceback.format_exc()}")
        return 1
    
    finally:
        # Cleanup if requested
        benchmark.cleanup()
    
    logger.success("✅ Benchmark completed successfully")
    return 0


if __name__ == "__main__":
    exit(main())
