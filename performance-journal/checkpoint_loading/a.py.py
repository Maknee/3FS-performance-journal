#!/usr/bin/env python3
"""
Benchmark script for Hugging Face model loading performance.
Only measures loading time from cache, not download time.
"""

import time
import argparse
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional
import json
import psutil
import torch

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

# Import our comprehensive usrbio utilities
sys.path.append(str(Path(__file__).parent.parent / "common"))
from usrbio_utils import (
    UsrbioDirectLoader,
    AllocationResource,
    ModelWithResources,
    install_usrbio_hooks, 
    remove_usrbio_hooks, 
    usrbio_from_pretrained,
    benchmark_usrbio_vs_standard,
    USRBIO_AVAILABLE,
    TORCH_AVAILABLE
)

from transformers import AutoModel

# Global reference to benchmark instance for hooks
_benchmark_instance = None

'''
export HF_ENABLE_PARALLEL_LOADING=1
export HF_PARALLEL_LOADING_WORKERS=4

Example R1 (distilled) models to benchmark:

# DeepSeek R1 Distilled Models
python benchmark.py --cache_dir /ssd/hf \
    --models \
    deepseek-ai/DeepSeek-R1-Distill-Qwen-1.5B \
    deepseek-ai/DeepSeek-R1-Distill-Qwen-7B \
    deepseek-ai/DeepSeek-R1-Distill-Qwen-14B \
    deepseek-ai/DeepSeek-R1-Distill-Qwen-32B \
    deepseek-ai/DeepSeek-R1-Distill-Llama-8B \
    --runs 5

python benchmark.py --cache_dir /ssd/hf \
    --drop-caches \
    --models \
    deepseek-ai/DeepSeek-R1-Distill-Qwen-32B \
    --runs 1


python benchmark.py --cache_dir /3fs/stage/fuse/hf \
    --drop-caches \
    --models \
    deepseek-ai/DeepSeek-R1-Distill-Qwen-32B \
    --runs 1

python benchmark.py \
    --drop-caches \
    --hf3fs-mount-point /3fs/stage \
    --cache_dir /3fs/stage/fuse/hf \
    --use-usrbio \
    --direct-sharded-loading \
    --models deepseek-ai/DeepSeek-R1-Distill-Qwen-7B \
    --usrbio-block-size $((1 << 30)) \
    --runs 1

# USRBIO accelerated benchmarks
python benchmark.py \
    --cache_dir /3fs/stage/fuse/hf \
    --use-usrbio \
    --hf3fs-mount-point /3fs/stage \
    --usrbio-block-size 1024 \
    --usrbio-priority -1 \
    --drop-caches \
    --models \
    deepseek-ai/DeepSeek-R1-Distill-Qwen-1.5B \
    deepseek-ai/DeepSeek-R1-Distill-Qwen-7B \
    deepseek-ai/DeepSeek-R1-Distill-Qwen-14B \
    deepseek-ai/DeepSeek-R1-Distill-Qwen-32B \
    deepseek-ai/DeepSeek-R1-Distill-Llama-8B \
    --runs 1


# Demonstrate new AllocationResource interface
python benchmark.py \
    --cache_dir /3fs/stage/fuse/hf \
    --use-usrbio \
    --demo-allocation-resource \
    --models deepseek-ai/DeepSeek-R1-Distill-Qwen-32B \
    --runs 1

# Benchmark file loading with new interface
python benchmark.py \
    --cache_dir /3fs/stage/fuse/hf \
    --use-usrbio \
    --benchmark-file-loading \
    --models deepseek-ai/DeepSeek-R1-Distill-Qwen-32B \
    --runs 1

# Compare different sizes of R1 distilled models
python benchmark.py --cache_dir /path/to/cache --models \
    deepseek-ai/DeepSeek-R1-Distill-Qwen-1.5B \
    deepseek-ai/DeepSeek-R1-Distill-Qwen-7B \
    deepseek-ai/DeepSeek-R1-Distill-Llama-8B \
    --output r1_size_comparison.json

# Cold read benchmarks (requires sudo)
sudo python benchmark.py --cache_dir /ssd/hf --models \
    deepseek-ai/DeepSeek-R1-Distill-Qwen-7B \
    --drop-caches --runs 3

'''


class ModelLoadingBenchmark:
    def __init__(self, cache_dir: str, use_usrbio: bool = False, hf3fs_mount_point: str = None, 
                 usrbio_block_size: int = 1<<30, usrbio_priority: int = 0, drop_caches: bool = False,
                 direct_sharded_loading: bool = False, max_concurrent: int = 8):
        self.cache_dir = Path(cache_dir)
        self.results = []
        self.use_usrbio = use_usrbio and USRBIO_AVAILABLE
        self.hf3fs_mount_point = hf3fs_mount_point
        self.usrbio_block_size = usrbio_block_size
        self.usrbio_priority = usrbio_priority
        self.drop_caches = drop_caches
        self.direct_sharded_loading = direct_sharded_loading
        self.max_concurrent = max_concurrent
        self.usrbio_stats = []
        
        if self.use_usrbio:
            if not USRBIO_AVAILABLE:
                logger.warning("⚠️  USRBIO requested but not available - falling back to standard loading")
                self.use_usrbio = False
            else:
                # Install comprehensive usrbio hooks
                success = install_usrbio_hooks(
                    hf3fs_mount_point=self.hf3fs_mount_point,
                    block_size=usrbio_block_size,
                    priority=usrbio_priority,
                    max_concurrent=max_concurrent
                )
                success = True
                if success:
                    logger.info(f"🚀 USRBIO enabled: mount={self.hf3fs_mount_point}, block_size={usrbio_block_size}")
                    if direct_sharded_loading:
                        logger.info(f"⚡ Direct sharded loading enabled with {max_concurrent} concurrent ops")
                else:
                    self.use_usrbio = False
        
        if self.drop_caches:
            logger.info("💧 CACHE DROPPING enabled - will drop system caches before each run")
            self._test_cache_drop_permissions()
    
    def _test_cache_drop_permissions(self):
        """Test if we have permissions to drop caches."""
        try:
            # Try to read the drop_caches file to see if we have access
            with open('/proc/sys/vm/drop_caches', 'r') as f:
                current_value = f.read().strip()
            logger.info(f"💧 Cache drop permissions: OK (current value: {current_value})")
        except PermissionError:
            logger.warning("⚠️  WARNING: No permission to drop caches. Run with sudo or disable --drop-caches")
        except Exception as e:
            logger.warning(f"⚠️  WARNING: Cannot access cache drop interface: {e}")
    
    def _drop_system_caches(self):
        """Drop system caches to ensure cold reads."""
        if not self.drop_caches:
            return
            
        try:
            logger.debug("💧 Dropping system caches...")
            
            # Sync to flush dirty buffers
            os.system('sync')
            
            # Drop page cache, dentries and inodes
            # 1 = page cache only
            # 2 = dentries and inodes  
            # 3 = page cache, dentries and inodes
            with open('/proc/sys/vm/drop_caches', 'w') as f:
                f.write('3\n')
            
            logger.debug("💧 System caches dropped successfully")
            
        except PermissionError:
            logger.error("⚠️  ERROR: No permission to drop caches. Run with sudo or disable --drop-caches")
        except Exception as e:
            logger.error(f"⚠️  ERROR: Failed to drop caches: {e}")
    
    def _load_model_with_direct_sharded(self, model_name: str):
        """Load model using direct usrbio sharded loading."""
        if not self.use_usrbio or not self.direct_sharded_loading:
            return None
            
        logger.info(f"🚀 Attempting direct usrbio sharded loading for {model_name}")
        
        # Use the cleaner usrbio_from_pretrained interface with resource tracking
        model_with_resources = usrbio_from_pretrained(
            model_name_or_path=model_name,
            cache_dir=str(self.cache_dir),
            hf3fs_mount_point=self.hf3fs_mount_point,
            block_size=self.usrbio_block_size,
            priority=self.usrbio_priority,
            max_concurrent=self.max_concurrent,
            torch_dtype=torch.float16 if torch.cuda.is_available() else torch.float32
        )
        
        return model_with_resources
    
    def benchmark_file_loading(self, file_paths: List[str], num_runs: int = 3):
        """Benchmark raw file loading using the new AllocationResource interface."""
        if not self.use_usrbio:
            logger.warning("⚠️  File loading benchmark requires USRBIO")
            return
            
        logger.info(f"\n🏁 RUNNING FILE LOADING BENCHMARKS (AllocationResource Interface)")
        logger.info(f"Testing {len(file_paths)} files with {num_runs} runs each")
        
        # Create loader with proper mount point
        if self.hf3fs_mount_point is None:
            from usrbio_utils import extract_mount_point
            self.hf3fs_mount_point = extract_mount_point(str(file_paths[0]))
            
        loader = UsrbioDirectLoader(
            hf3fs_mount_point=self.hf3fs_mount_point,
            block_size=self.usrbio_block_size,
            priority=self.usrbio_priority
        )
        
        total_results = []
        
        for run in range(num_runs):
            logger.info(f"\n--- File Loading Run {run + 1}/{num_runs} ---")
            self._drop_system_caches()
            
            start_time = time.perf_counter()
            
            # Test single file loading
            single_resource = None
            if file_paths:
                logger.debug(f"🚀 Testing single file: {Path(file_paths[0]).name}")
                single_resource = loader.read_file(file_paths[0])
                
                try:
                    if single_resource.success:
                        logger.info(f"   Single file: {single_resource.load_time:.3f}s, {single_resource.file_size / (1024**3) / single_resource.load_time:.2f} GB/s")
                    else:
                        logger.error(f"   Single file failed: {single_resource.error}")
                finally:
                    # Always deallocate the resource
                    if single_resource:
                        loader.deallocate(single_resource)
                
            # Test multiple file loading
            multi_resources = None
            if len(file_paths) > 1:
                logger.debug(f"🚀 Testing multiple files: {len(file_paths)} files")
                multi_resources = loader.read_files(file_paths)
                
                try:
                    total_size = sum(r.file_size for r in multi_resources.values() if r.success)
                    successful_files = sum(1 for r in multi_resources.values() if r.success)
                    
                    multi_end_time = time.perf_counter()
                    multi_total_time = multi_end_time - start_time
                    
                    logger.info(f"   Multiple files: {multi_total_time:.3f}s, {successful_files}/{len(file_paths)} files")
                    logger.info(f"   Total data: {total_size / (1024**3):.2f} GB, {total_size / (1024**3) / multi_total_time:.2f} GB/s")
                    
                finally:
                    # Always deallocate all resources
                    if multi_resources:
                        for resource in multi_resources.values():
                            loader.deallocate(resource)
                
            total_time = time.perf_counter() - start_time
            total_results.append(total_time)
        
        # Summary
        if total_results:
            avg_time = sum(total_results) / len(total_results)
            logger.success(f"\n🎯 File Loading Summary: {avg_time:.3f}s average over {num_runs} runs")
        
        return total_results
    
    def benchmark_model_loading(self, model_name: str, num_runs: int = 3) -> Dict:
        """Benchmark the loading time of a specific model."""
        logger.info(f"\nBenchmarking {model_name} loading...")
        
        loading_times = []
        memory_usage = []
        usrbio_method_used = False
        
        for run in range(num_runs):
            # Drop system caches for cold read benchmark
            self._drop_system_caches()
            
            # Clear any cached model from memory
            if 'model' in locals():
                del model
            torch.cuda.empty_cache() if torch.cuda.is_available() else None
            
            # Measure memory before loading
            memory_before = psutil.Process().memory_info().rss / 1024 / 1024  # MB
            
            # Benchmark loading time (includes download if not cached)
            start_time = time.perf_counter()
            model = None
            model_with_resources = None
            
            # Try direct sharded loading first if enabled
            if self.direct_sharded_loading:
                model_with_resources = self._load_model_with_direct_sharded(model_name)
                if model_with_resources is not None:
                    model = model_with_resources.model
                    usrbio_method_used = True
                    logger.success(f"✅ Used direct usrbio sharded loading")
            
            # Fall back to standard loading (with hooks if usrbio enabled)
            if model is None:
                model = AutoModel.from_pretrained(
                    model_name,
                    cache_dir=self.cache_dir,
                    torch_dtype=torch.float16 if torch.cuda.is_available() else torch.float32
                )
                if self.use_usrbio:
                    logger.success(f"✅ Used standard loading with usrbio hooks")
                else:
                    logger.info(f"✅ Used standard loading")
            
            end_time = time.perf_counter()
            
            # Measure memory after loading
            memory_after = psutil.Process().memory_info().rss / 1024 / 1024  # MB
            
            loading_time = end_time - start_time
            memory_diff = memory_after - memory_before
            
            loading_times.append(loading_time)
            memory_usage.append(memory_diff)
            
            logger.info(f"  Run {run + 1}: {loading_time:.3f}s, Memory: +{memory_diff:.1f}MB")
            
            # Clean up model resources for this run
            if model_with_resources:
                try:
                    model_with_resources.deallocate_resources()
                    logger.debug(f"🧹 Cleaned up USRBIO resources for run {run + 1}")
                except Exception as e:
                    logger.debug(f"⚠️  Resource cleanup failed for run {run + 1}: {e}")
            
            # Clear model from memory before next run
            if 'model' in locals():
                del model
            if 'model_with_resources' in locals():
                del model_with_resources
                    
        if not loading_times:
            return None
            
        result = {
            'model_name': model_name,
            'num_runs': len(loading_times),
            'loading_times': loading_times,
            'avg_loading_time': sum(loading_times) / len(loading_times),
            'min_loading_time': min(loading_times),
            'max_loading_time': max(loading_times),
            'memory_usage_mb': memory_usage,
            'avg_memory_usage_mb': sum(memory_usage) / len(memory_usage),
            'device': 'cuda' if torch.cuda.is_available() else 'cpu',
            'usrbio_enabled': self.use_usrbio,
            'direct_sharded_loading': usrbio_method_used
        }
        
        self.results.append(result)
        return result
    
    def benchmark_multiple_models(self, models: List[Dict], num_runs: int = 3):
        """Benchmark multiple models."""
        logger.info(f"Starting benchmark with {len(models)} models, {num_runs} runs each")
        logger.info(f"Cache directory: {self.cache_dir}")
        logger.info(f"Device: {'CUDA' if torch.cuda.is_available() else 'CPU'}")
        if self.use_usrbio:
            logger.info(f"🚀 USRBIO ACCELERATION: Enabled")
            logger.debug(f"   Mount point: {self.hf3fs_mount_point}")
            logger.debug(f"   Block size: {self.usrbio_block_size}")
            logger.debug(f"   Priority: {self.usrbio_priority}")
            logger.debug(f"   Direct sharded loading: {self.direct_sharded_loading}")
        
        for i, model_info in enumerate(models, 1):
            logger.info(f"\n--- Model {i}/{len(models)} ---")
            result = self.benchmark_model_loading(
                model_info, 
                num_runs
            )
            
            if result:
                logger.info(f"Average loading time: {result['avg_loading_time']:.3f}s")
                logger.info(f"Average memory usage: +{result['avg_memory_usage_mb']:.1f}MB")
                if result.get('usrbio_enabled'):
                    method = 'ACTIVE' if result.get('direct_sharded_loading') else 'USED (hooks)'
                    logger.success(f"🚀 USRBIO acceleration was {method}")
    
    def save_results(self, output_file: str):
        """Save benchmark results to JSON file."""
        with open(output_file, 'w') as f:
            json.dump(self.results, f, indent=2)
        logger.info(f"\nResults saved to {output_file}")
    
    def print_summary(self):
        """Print a summary of all benchmark results."""
        if not self.results:
            logger.warning("No benchmark results to display.")
            return
            
        logger.info("\n" + "="*80)
        logger.info("BENCHMARK SUMMARY")
        logger.info("="*80)
        
        for result in sorted(self.results, key=lambda x: x['avg_loading_time']):
            acceleration_info = ""
            if result.get('usrbio_enabled'):
                if result.get('direct_sharded_loading'):
                    acceleration_info = " (🚀 USRBIO DIRECT)"
                else:
                    acceleration_info = " (🚀 USRBIO HOOKS)"
                    
            logger.info(f"{result['model_name']:<40} | "
                  f"{result['avg_loading_time']:>8.3f}s | "
                  f"{result['avg_memory_usage_mb']:>8.1f}MB | "
                  f"{acceleration_info}")
    
    def cleanup(self):
        """Cleanup usrbio hooks if installed."""
        if self.use_usrbio:
            remove_usrbio_hooks()
            logger.info("🔓 USRBIO hooks removed")

def main():
    parser = argparse.ArgumentParser(
        description="Benchmark Hugging Face model loading performance"
    )
    parser.add_argument(
        '--cache_dir', 
        type=str, 
        required=True,
        help='Directory where Hugging Face models are cached'
    )
    parser.add_argument(
        '--models',
        nargs='+',
        help='Specific model names to benchmark (default: common models)'
    )
    parser.add_argument(
        '--runs',
        type=int,
        default=3,
        help='Number of runs per model (default: 3)'
    )
    parser.add_argument(
        '--output',
        type=str,
        default='benchmark_results.json',
        help='Output file for results (default: benchmark_results.json)'
    )
    parser.add_argument(
        '--use-usrbio',
        action='store_true',
        help='Enable usrbio for distributed filesystem acceleration'
    )
    parser.add_argument(
        '--hf3fs-mount-point',
        type=str,
        help='hf3fs mount point (auto-detected if not specified)'
    )
    parser.add_argument(
        '--usrbio-block-size',
        type=int,
        default=1<<30,
        help='Block size for usrbio operations (default: 1GB)'
    )
    parser.add_argument(
        '--usrbio-priority',
        type=int,
        choices=[-1, 0, 1],
        default=0,
        help='I/O priority: -1=HIGH, 0=NORMAL, 1=LOW (default: 0)'
    )
    parser.add_argument(
        '--drop-caches',
        action='store_true',
        help='Drop system caches before each run for cold read benchmarks (requires sudo)'
    )
    parser.add_argument(
        '--direct-sharded-loading',
        action='store_true',
        help='Use direct usrbio sharded checkpoint loading (requires --use-usrbio)'
    )
    parser.add_argument(
        '--max-concurrent',
        type=int,
        default=8,
        help='Maximum concurrent file operations for usrbio (default: 8)'
    )
    parser.add_argument(
        '--benchmark-file-loading',
        action='store_true',
        help='Benchmark raw file loading performance (usrbio vs standard)'
    )
    parser.add_argument(
        '--demo-allocation-resource',
        action='store_true',
        help='Demonstrate the AllocationResource interface step by step (requires --use-usrbio)'
    )
    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Enable verbose debug logging'
    )
    
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
    
    # Verify cache directory exists
    if not os.path.exists(args.cache_dir):
        logger.error(f"Error: Cache directory {args.cache_dir} does not exist.")
        sys.exit(1)
    
    # Validate direct sharded loading option
    if args.direct_sharded_loading and not args.use_usrbio:
        logger.error("Error: --direct-sharded-loading requires --use-usrbio")
        sys.exit(1)
    
    # Initialize benchmark with usrbio parameters
    benchmark = ModelLoadingBenchmark(
        args.cache_dir,
        use_usrbio=args.use_usrbio,
        hf3fs_mount_point=args.hf3fs_mount_point,
        usrbio_block_size=args.usrbio_block_size,
        usrbio_priority=args.usrbio_priority,
        drop_caches=args.drop_caches,
        direct_sharded_loading=args.direct_sharded_loading,
        max_concurrent=args.max_concurrent
    )
    
    # Set global reference for any remaining hooks
    global _benchmark_instance
    _benchmark_instance = benchmark
    
    try:
        # Prepare models list
        if not args.models:
            logger.error("No specific models provided, using default model set.")
            sys.exit(1)

        models = args.models
        
        # Run file loading benchmarks if requested
        if args.benchmark_file_loading and args.use_usrbio:
            logger.info("\n🏁 RUNNING FILE LOADING BENCHMARKS")
            # Find some model files to benchmark
            test_files = []
            for model_name in args.models[:1]:  # Just test first model
                model_path = Path(args.cache_dir) / f"models--{model_name.replace('/', '--')}" / "snapshots"
                if model_path.exists():
                    snapshot_dirs = list(model_path.glob("*"))
                    if snapshot_dirs:
                        files = list(snapshot_dirs[0].glob("*.safetensors")) + list(snapshot_dirs[0].glob("*.bin"))
                        test_files.extend([str(f) for f in files[:3]])  # Test up to 3 files
            
            if test_files:
                # Use new AllocationResource interface for file loading benchmark
                benchmark.benchmark_file_loading(test_files, runs=3)
                
                # Also run comparison benchmark if available
                try:
                    benchmark_usrbio_vs_standard(
                        test_files, 
                        hf3fs_mount_point=args.hf3fs_mount_point,
                        runs=3
                    )
                except Exception as e:
                    logger.warning(f"⚠️  Standard comparison benchmark failed: {e}")
            else:
                logger.warning("⚠️  No model files found for file loading benchmark")
        
        # Run model benchmarks
        benchmark.benchmark_multiple_models(models, args.runs)
        
        # Display and save results
        benchmark.print_summary()
        benchmark.save_results(args.output)
        
    finally:
        # Always cleanup hooks
        benchmark.cleanup()


if __name__ == "__main__":
    main()
