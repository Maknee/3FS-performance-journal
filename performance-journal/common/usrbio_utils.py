"""
USRBIO utilities for high-performance transformer model loading and saving.
Provides direct async I/O operations and hooks for accelerated loading and checkpointing.
"""

import os
import time
import json
import gc
from pathlib import Path
import copy
# Removed unused imports
from typing import List, Dict, Tuple, Optional, Any, Union
from dataclasses import dataclass
import concurrent.futures
from concurrent.futures import ThreadPoolExecutor
import multiprocessing.shared_memory
from functools import partial
from uuid import uuid4
from transformers import (
    PreTrainedModel, 
    AutoConfig,
)

# Configure loguru for nice structured logging
from loguru import logger
import sys

USRBIO_DEFAULT_BLOCK_SIZE = 1<<30
USRBIO_DEFAULT_CHUNK_SIZE = 1<<30

# Remove default handler and add custom one with nice formatting
logger.remove()
logger.add(
    sys.stderr,
    format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan> | <level>{message}</level>",
    level="DEBUG",
    colorize=True
)

try:
    import hf3fs_fuse.io as h3io
    import hf3fs_py_usrbio as h3fio
    from hf3fs_py_usrbio import register_fd, deregister_fd, extract_mount_point
    USRBIO_AVAILABLE = True
    logger.info("🚀 USRBIO core available for direct I/O operations")
except ImportError:
    USRBIO_AVAILABLE = False
    h3io = None
    h3fio = None
    logger.warning("❌ USRBIO not available")

try:
    import safetensors.torch
    import torch
    from io import BytesIO
    TORCH_AVAILABLE = True
    logger.info("🚀 Torch and safetensors available")
except ImportError:
    TORCH_AVAILABLE = False
    safetensors = None
    torch = None
    BytesIO = None
    logger.warning("❌ Torch/safetensors not available")


@dataclass
class AllocationResource:
    """Resource tracking for USRBIO operations that must be deallocated."""
    file_path: str
    file_size: int
    shm: multiprocessing.shared_memory.SharedMemory
    iov: Any
    buffer: Any
    fd: Optional[int] = None
    ior: Optional[Any] = None
    success: bool = True
    error: Optional[str] = None
    load_time: float = 0.0
    
    def __post_init__(self):
        """Mark resource as allocated."""
        self._allocated = True
        self._deallocated = False
    
    @property
    def is_allocated(self) -> bool:
        """Check if resource is still allocated."""
        return self._allocated and not self._deallocated
    
    def _mark_deallocated(self):
        """Internal method to mark resource as deallocated."""
        self._deallocated = True


@dataclass
class ModelWithResources:
    """Container for model and its associated USRBIO resources that need deallocation."""
    model: PreTrainedModel
    resources: List[AllocationResource]
    loader: Optional['UsrbioDirectLoader'] = None
    
    def deallocate_resources(self):
        """Deallocate all associated USRBIO resources."""
        if self.loader and self.resources:
            resource_count = len(self.resources)
            for resource in self.resources:
                try:
                    self.loader.deallocate(resource)
                except Exception as e:
                    logger.debug(f"⚠️  Failed to deallocate resource {resource.file_path}: {e}")
            self.resources.clear()
            logger.debug(f"🧹 Deallocated {resource_count} USRBIO resources")


@dataclass
class BufferAllocation:
    """Result of buffer allocation."""
    file_path: str
    file_size: int
    shm: multiprocessing.shared_memory.SharedMemory
    iov: Any
    buffer: Any
    
    def deallocate(self):
        """Clean up this allocation's resources."""
        cleanup_usrbio_resource(self)


def cleanup_usrbio_resource(resource) -> bool:
    """
    Common cleanup function for USRBIO resources.
    
    Handles cleanup of file descriptors, io_urings, iovectors, and shared memory.
    Safe to call multiple times on the same resource.
    
    Args:
        resource: AllocationResource, BufferAllocation, or FileReadResult to clean up
        
    Returns:
        bool: True if cleanup was successful, False otherwise
    """
    cleanup_success = True
    
    try:
        # Clean up file descriptor if present
        if hasattr(resource, 'fd') and resource.fd is not None:
            try:
                h3fio.deregister_fd(resource.fd)
                os.close(resource.fd)
                resource.fd = None
            except Exception as e:
                logger.debug(f"⚠️  Failed to cleanup fd: {e}")
                cleanup_success = False
        
        # Clean up io_uring if present  
        if hasattr(resource, 'ior') and resource.ior is not None:
            try:
                del resource.ior
                resource.ior = None
            except Exception as e:
                logger.debug(f"⚠️  Failed to cleanup ior: {e}")
                cleanup_success = False
        
        # Clean up iovec if present
        if hasattr(resource, 'iov') and resource.iov is not None:
            try:
                del resource.iov
                resource.iov = None
            except Exception as e:
                logger.debug(f"⚠️  Failed to cleanup iov: {e}")
                cleanup_success = False
        
        # Clean up shared memory if present
        if hasattr(resource, 'shm') and resource.shm is not None:
            try:
                resource.shm.close()
                resource.shm.unlink()
                resource.shm = None
            except Exception as e:
                logger.debug(f"⚠️  Failed to cleanup shm: {e}")
                cleanup_success = False
        
        # Mark as deallocated if it's an AllocationResource
        if hasattr(resource, '_mark_deallocated'):
            resource._mark_deallocated()
            
    except Exception as e:
        logger.error(f"❌ Cleanup failed: {e}")
        cleanup_success = False
    
    return cleanup_success


@dataclass
class FileReadResult:
    """Result of a single file read."""
    buffer: Any
    shm: multiprocessing.shared_memory.SharedMemory
    iov: Any
    file_size: int
    file_path: str
    success: bool = True
    error: Optional[str] = None
    load_time: float = 0.0


@dataclass
class FileWriteResult:
    """Result of a single file write."""
    file_path: str
    file_size: int
    success: bool = True
    error: Optional[str] = None
    write_time: float = 0.0
    throughput_gbps: float = 0.0


class UsrbioDirectWriter:
    """Direct usrbio writer using low-level async I/O operations."""
    
    def __init__(self, hf3fs_mount_point: str, block_size: int = USRBIO_DEFAULT_BLOCK_SIZE, 
                 chunk_size: int = USRBIO_DEFAULT_CHUNK_SIZE, priority: int = 0):
        self.hf3fs_mount_point = hf3fs_mount_point
        self.block_size = block_size
        self.chunk_size = chunk_size
        self.priority = priority
        self.stats = []
        
    def write_file(self, file_path: str, data: bytes) -> FileWriteResult:
        """Write file using direct usrbio async operations."""
        start_time = time.perf_counter()
        
        try:
            logger.debug(f"🚀 Direct async writing: {Path(file_path).name} ({len(data)} bytes)")
            
            # Create shared memory buffer for the data
            shm = multiprocessing.shared_memory.SharedMemory(size=len(data), create=True)
            
            # Copy data to shared memory
            copy_start = time.perf_counter()
            shm.buf[:len(data)] = data
            copy_time = time.perf_counter() - copy_start
            
            # Create iovec for the buffer
            iov = h3io.make_iovec(shm, self.hf3fs_mount_point, block_size=self.block_size, numa=-1)
            
            # Open and register file descriptor for writing
            fd = os.open(file_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
            h3fio.register_fd(fd)
            
            # Create ioring for write operations
            ior = h3io.make_ioring(
                self.hf3fs_mount_point,
                entries=1,
                for_read=False,  # For writing
                io_depth=0,
                priority=self.priority,
                numa=-1
            )
            
            # Submit write in chunks
            submit_start = time.perf_counter()
            total_written = 0
            data_size = len(data)
            
            # Calculate number of chunks needed
            if self.chunk_size <= 0:
                # If chunk_size is 0 or negative, write entire file as one chunk
                num_chunks = 1
                effective_chunk_size = data_size
            else:
                num_chunks = (data_size + self.chunk_size - 1) // self.chunk_size
                effective_chunk_size = self.chunk_size
            logger.debug(f"  🔧 Writing {data_size} bytes in {num_chunks} chunks of {effective_chunk_size} bytes")
            
            for chunk_idx in range(num_chunks):
                if self.chunk_size <= 0:
                    # Single chunk for entire file
                    file_offset = 0
                    buffer_offset = 0
                    current_chunk_size = data_size
                else:
                    file_offset = chunk_idx * self.chunk_size
                    buffer_offset = chunk_idx * self.chunk_size
                    current_chunk_size = min(self.chunk_size, data_size - file_offset)
                
                logger.debug(f"    📤 Chunk {chunk_idx + 1}/{num_chunks}: offset={file_offset}, size={current_chunk_size}")

                # Prepare write for this chunk
                ior.prepare2(iov,
                             read=False,
                             fd=fd,
                             off=file_offset,
                             ptr_offset=buffer_offset,
                             length=current_chunk_size,
                             userdata=chunk_idx)
                
                # Submit and wait for this chunk
                result = ior.submit().wait(min_results=1)[0]
                
                if result.result < 0:
                    raise OSError(-result.result, f"Write chunk {chunk_idx} failed with error {-result.result}")
                
                if result.result != current_chunk_size:
                    raise ValueError(f"Partial write in chunk {chunk_idx}: wrote {result.result}, expected {current_chunk_size}")
                
                total_written += result.result
                logger.debug(f"    ✅ Chunk {chunk_idx + 1} written: {result.result} bytes")
            
            wait_time = time.perf_counter() - submit_start
            
            if total_written != data_size:
                raise ValueError(f"Total write mismatch: wrote {total_written}, expected {data_size}")
            
            # Clean up
            h3fio.deregister_fd(fd)
            os.close(fd)
            del ior
            del iov
            shm.close()
            shm.unlink()
            
            end_time = time.perf_counter()
            total_time = end_time - start_time
            throughput_gbps = (len(data) / (1024**3)) / total_time
            
            logger.success(f"✅ Wrote {len(data) / (1024**2):.1f}MB in {total_time:.3f}s ({throughput_gbps:.2f} GB/s)")
            
            return FileWriteResult(
                file_path=file_path,
                file_size=len(data),
                success=True,
                error=None,
                write_time=total_time,
                throughput_gbps=throughput_gbps
            )
            
        except Exception as e:
            end_time = time.perf_counter()
            
            logger.error(f"❌ Failed to write {Path(file_path).name}: {e}")
            return FileWriteResult(
                file_path=file_path,
                file_size=len(data),
                success=False,
                error=str(e),
                write_time=end_time - start_time,
                throughput_gbps=0.0
            )
    
    def write_files(self, files_data: Dict[str, bytes]) -> Dict[str, FileWriteResult]:
        """Write multiple files using USRBIO operations."""
        results = {}
        
        for file_path, data in files_data.items():
            result = self.write_file(file_path, data)
            results[file_path] = result
            
        return results


class UsrbioDirectLoader:
    """Direct usrbio loader with resource tracking interface."""
    
    def __init__(self, hf3fs_mount_point: str, block_size: int = USRBIO_DEFAULT_BLOCK_SIZE, 
                 chunk_size: int = USRBIO_DEFAULT_CHUNK_SIZE, priority: int = 0):
        self.hf3fs_mount_point = hf3fs_mount_point
        self.block_size = block_size
        self.chunk_size = chunk_size
        self.priority = priority
        
    def deallocate(self, resource: AllocationResource) -> bool:
        """
        Deallocate USRBIO resources.
        
        Args:
            resource: AllocationResource to deallocate
            
        Returns:
            bool: True if deallocation was successful
        """
        if not isinstance(resource, AllocationResource):
            logger.error("❌ Invalid resource type for deallocation")
            return False
            
        if not resource.is_allocated:
            logger.warning("⚠️  Resource already deallocated")
            return True
            
        logger.debug(f"🧹 Deallocating resource: {resource.file_path}")
        return cleanup_usrbio_resource(resource)
        
    def allocate_buffer(self, file_path: str) -> AllocationResource:
        """Allocate shared memory buffer for file."""
        if not USRBIO_AVAILABLE:
            raise RuntimeError("USRBIO not available")
            
        file_size = os.path.getsize(file_path)

        iov = h3fio.iovec(self.hf3fs_mount_point, file_size, self.block_size, numa=-1)
        if iov.result != 0:
            raise RuntimeError(f"Failed to allocate iovec: {iov.result}")
        
        return AllocationResource(
            file_path=file_path,
            file_size=file_size,
            shm=None,
            iov=iov,
            buffer=iov.buffer,
        )

    def prepare_read(self, resource: AllocationResource):
        """Prepare async read by opening file descriptor and creating io_uring."""
        if not USRBIO_AVAILABLE:
            raise RuntimeError("USRBIO not available")
            
        # Open and register file descriptor
        fd = os.open(resource.file_path, os.O_RDONLY)
        h3fio.register_fd(fd)

        # Calculate number of chunks needed
        if self.chunk_size <= 0:
            # If chunk_size is 0 or negative, read entire file as one chunk
            num_chunks = 1
        else:
            num_chunks = (resource.file_size + self.chunk_size - 1) // self.chunk_size
        
        # Create ioring with enough entries for all chunks
        ior = h3fio.ioring(
            self.hf3fs_mount_point,
            entries=num_chunks,
            for_read=True,
            io_depth=0,
            priority=self.priority,
            numa=-1,
            flags=0
        )
        
        logger.debug(f"  🔧 Prepared for reading {resource.file_size} bytes in {num_chunks} chunks of {self.chunk_size} bytes")
        
        # Store fd and ior in the resource
        resource.fd = fd
        resource.ior = ior
        resource.num_chunks = num_chunks
        
        return fd, ior
    
    def submit_read(self, resource: AllocationResource):
        """Submit all read operations without waiting for completion."""
        if not USRBIO_AVAILABLE:
            raise RuntimeError("USRBIO not available")
            
        if not hasattr(resource, 'fd') or not hasattr(resource, 'ior'):
            raise RuntimeError("Resource not prepared - call prepare_read() first")
        
        fd = resource.fd
        ior = resource.ior
        num_chunks = resource.num_chunks
        
        logger.debug(f"  📤 Submitting {num_chunks} read operations...")
        
        # Submit all chunks at once
        userdata_submitted = []
        for chunk_idx in range(num_chunks):
            if self.chunk_size <= 0:
                # Single chunk for entire file
                file_offset = 0
                buffer_offset = 0
                current_chunk_size = resource.file_size
            else:
                file_offset = chunk_idx * self.chunk_size
                buffer_offset = chunk_idx * self.chunk_size
                current_chunk_size = min(self.chunk_size, resource.file_size - file_offset)
            
            logger.debug(f"    📥 Queuing chunk {chunk_idx + 1}/{num_chunks}: offset={file_offset}, size={current_chunk_size}, userdata={chunk_idx}")
            
            # Prepare read for this chunk
            ior.prepare2(resource.iov,
                         read=True,
                         fd=fd,
                         off=file_offset,
                         ptr_offset=buffer_offset,
                         length=current_chunk_size,
                         userdata=chunk_idx)
            userdata_submitted.append(chunk_idx)
        
        # Submit all operations at once and return the submitted io_uring
        submitted_ior = ior.submit()
        resource.submitted_ior = submitted_ior
        
        logger.debug(f"  ✅ Submitted {num_chunks} read operations with userdata: {userdata_submitted}")
        return submitted_ior
    
    def wait_read(self, resource: AllocationResource):
        """Wait for all read operations to complete and validate results."""
        if not USRBIO_AVAILABLE:
            raise RuntimeError("USRBIO not available")
            
        if not hasattr(resource, 'submitted_ior'):
            raise RuntimeError("No submitted operations - call submit_read() first")
        
        submitted_ior = resource.submitted_ior
        num_chunks = resource.num_chunks
        
        logger.debug(f"  ⏳ Waiting for {num_chunks} read operations to complete...")
        
        # Wait for all operations to complete
        results = submitted_ior.wait(min_results=num_chunks, max_results=num_chunks)

        # Since we use a single IOV and results are filled with the result from the last IOV,
        # only check the last result for errors
        last_result = results[-1]
        if last_result.result < 0:
            raise OSError(-last_result.result, f"Read operation failed with error {-last_result.result}")
        
        logger.debug(f"  ✅ All {num_chunks} operations completed successfully")
        
        # Clean up the submitted_ior reference
        delattr(resource, 'submitted_ior')
        
        return resource.file_size
    
    def read_file(self, file_path: str) -> AllocationResource:
        """
        Read a single file and return AllocationResource.
        
        User must call deallocate() on the returned resource when done.
        
        Args:
            file_path: Path to file to read
            
        Returns:
            AllocationResource containing the loaded data and resources
        """
        return self.read_files([file_path])[file_path]
    
    def read_file_async(self, file_path: str) -> AllocationResource:
        """
        Read a single file using the three-step async approach for maximum control.
        
        This method demonstrates how to use prepare_read(), submit_read(), and wait_read()
        separately for advanced use cases where you want to overlap operations.
        
        User must call deallocate() on the returned resource when done.
        
        Args:
            file_path: Path to file to read
            
        Returns:
            AllocationResource containing the loaded data and resources
        """
        start_time = time.perf_counter()
        logger.debug(f"🚀 Async reading file: {os.path.basename(file_path)}")
        
        try:
            # Step 1: Allocate buffer
            logger.debug("  📦 Step 1: Allocating buffer...")
            step1_start = time.perf_counter()
            resource = self.allocate_buffer(file_path)
            step1_time = time.perf_counter() - step1_start
            logger.debug(f"  ⏱️  Buffer allocation took: {step1_time:.3f}s")
            
            # Step 2: Prepare read (open file, create io_uring)
            logger.debug("  🔧 Step 2: Preparing read...")
            step2_start = time.perf_counter()
            self.prepare_read(resource)
            step2_time = time.perf_counter() - step2_start
            logger.debug(f"  ⏱️  Read preparation took: {step2_time:.3f}s")
            
            # Step 3: Submit read operations
            logger.debug("  📤 Step 3: Submitting read...")
            step3_start = time.perf_counter()
            self.submit_read(resource)
            step3_time = time.perf_counter() - step3_start
            logger.debug(f"  ⏱️  Read submission took: {step3_time:.3f}s")
            
            # Step 4: Wait for completion
            logger.debug("  ⏳ Step 4: Waiting for completion...")
            step4_start = time.perf_counter()
            total_read = self.wait_read(resource)
            step4_time = time.perf_counter() - step4_start
            logger.debug(f"  ⏱️  Read completion took: {step4_time:.3f}s")
            
            total_time = time.perf_counter() - start_time
            throughput_gbps = (resource.file_size / (1024**3)) / total_time
            
            # Mark as successful
            resource.success = True
            resource.error = None
            resource.load_time = total_time
            
            logger.success(f"✅ Async file read completed in {total_time:.3f}s ({throughput_gbps:.2f} GB/s)")
            logger.debug(f"   Step breakdown: alloc={step1_time:.1f}s, prepare={step2_time:.1f}s, submit={step3_time:.1f}s, wait={step4_time:.1f}s")
            
            return resource
            
        except Exception as e:
            logger.error(f"❌ Async file read failed: {e}")
            # Mark as failed
            resource.success = False
            resource.error = str(e)
            resource.load_time = time.perf_counter() - start_time
            
            # Clean up on failure
            cleanup_usrbio_resource(resource)
            
            return resource
    
    def read_files_advanced_async(self, file_paths: List[str]) -> Dict[str, AllocationResource]:
        """
        Read multiple files using the three-step async approach with maximum parallelization.
        
        This demonstrates the most efficient way to use prepare_read(), submit_read(), and wait_read()
        for multiple files, allowing maximum overlap of operations.
        
        User must call deallocate() on each returned AllocationResource when done.
        
        Args:
            file_paths: List of file paths to read
            
        Returns:
            Dict mapping file paths to AllocationResource objects
        """
        if not file_paths:
            return {}
            
        start_time = time.perf_counter()
        logger.debug(f"🚀 Advanced async reading {len(file_paths)} files")
        
        # Phase 1: Allocate all buffers
        logger.debug("  📦 Phase 1: Allocating all buffers...")
        phase1_start = time.perf_counter()
        resources = []
        for file_path in file_paths:
            try:
                resource = self.allocate_buffer(file_path)
                resources.append(resource)
            except Exception as e:
                logger.error(f"❌ Failed to allocate buffer for {file_path}: {e}")
                # Create a failed resource for consistency
                resource = AllocationResource(
                    file_path=file_path,
                    file_size=0,
                    shm=None,
                    iov=None,
                    buffer=None,
                    success=False,
                    error=str(e)
                )
                resources.append(resource)
        phase1_time = time.perf_counter() - phase1_start
        logger.debug(f"  ⏱️  Buffer allocation took: {phase1_time:.3f}s")
        
        # Phase 2: Prepare all reads (open files, create io_urings)
        logger.debug("  🔧 Phase 2: Preparing all reads...")
        phase2_start = time.perf_counter()
        for resource in resources:
            if resource.success:  # Only prepare successful allocations
                try:
                    self.prepare_read(resource)
                except Exception as e:
                    logger.error(f"❌ Failed to prepare read for {resource.file_path}: {e}")
                    resource.success = False
                    resource.error = str(e)
        phase2_time = time.perf_counter() - phase2_start
        logger.debug(f"  ⏱️  Read preparation took: {phase2_time:.3f}s")
        
        # Phase 3: Submit all read operations
        logger.debug("  📤 Phase 3: Submitting all reads...")
        phase3_start = time.perf_counter()
        for resource in resources:
            if resource.success:  # Only submit successful preparations
                try:
                    self.submit_read(resource)
                except Exception as e:
                    logger.error(f"❌ Failed to submit read for {resource.file_path}: {e}")
                    resource.success = False
                    resource.error = str(e)
        phase3_time = time.perf_counter() - phase3_start
        logger.debug(f"  ⏱️  Read submission took: {phase3_time:.3f}s")
        
        # Phase 4: Wait for all completions
        logger.debug("  ⏳ Phase 4: Waiting for all completions...")
        phase4_start = time.perf_counter()
        results = {}
        for i, resource in enumerate(resources):
            file_start_time = time.perf_counter()
            logger.debug(f"    📥 Waiting for file {i+1}/{len(resources)}: {os.path.basename(resource.file_path)}")
            
            if resource.success:  # Only wait for successful submissions
                try:
                    total_read = self.wait_read(resource)
                    file_load_time = time.perf_counter() - file_start_time
                    
                    # Success
                    resource.load_time = file_load_time
                    resource.success = True
                    resource.error = None
                    
                    logger.debug(f"    ✅ File {i+1} completed: {file_load_time:.3f}s")
                    
                except Exception as e:
                    file_load_time = time.perf_counter() - file_start_time
                    logger.error(f"❌ Wait failed for {resource.file_path}: {e}")
                    
                    # Mark as failed and clean up
                    resource.success = False
                    resource.error = str(e)
                    resource.load_time = file_load_time
                    cleanup_usrbio_resource(resource)
            else:
                # Already failed in earlier phase
                resource.load_time = 0.0
                if not hasattr(resource, 'error') or resource.error is None:
                    resource.error = "Failed in preparation phase"
            
            results[resource.file_path] = resource
        
        phase4_time = time.perf_counter() - phase4_start
        total_time = time.perf_counter() - start_time
        
        # Calculate statistics
        successful_resources = [r for r in results.values() if r.success]
        total_size = sum(r.file_size for r in successful_resources)
        avg_throughput = (total_size / (1024**3)) / total_time if total_time > 0 else 0
        
        logger.success(f"✅ Advanced async read completed in {total_time:.3f}s")
        logger.debug(f"   Files: {len(successful_resources)}/{len(file_paths)} successful")
        logger.debug(f"   Total size: {total_size / (1024**2):.1f}MB")
        logger.debug(f"   Throughput: {avg_throughput:.2f} GB/s")
        logger.debug(f"   Phase breakdown: alloc={phase1_time:.1f}s, prepare={phase2_time:.1f}s, submit={phase3_time:.1f}s, wait={phase4_time:.1f}s")
        
        return results
     
    def read_files(self, file_paths: List[str]) -> Dict[str, AllocationResource]:
        """
        Read multiple files using multiple io-urings, no threading.
        
        User must call deallocate() on each returned AllocationResource when done.
        
        Args:
            file_paths: List of file paths to read
            
        Returns:
            Dict mapping file paths to AllocationResource objects
        """
        if not file_paths:
            return {}
            
        start_time = time.perf_counter()
        logger.debug(f"🚀 Starting batch read of {len(file_paths)} files")
        
        # Phase 1: Allocate all buffers
        logger.debug("  📦 Phase 1: Allocating buffers...")
        phase1_start = time.perf_counter()
        resources = []
        for file_path in file_paths:
            resource = self.allocate_buffer(file_path)
            resources.append(resource)
        phase1_time = time.perf_counter() - phase1_start
        logger.debug(f"  ⏱️  Buffer allocation took: {phase1_time:.3f}s")
        
        # Phase 2: Prepare all reads (open files, create io_urings)
        logger.debug("  🔧 Phase 2: Preparing reads...")
        phase2_start = time.perf_counter()
        for resource in resources:
            self.prepare_read(resource)
        phase2_time = time.perf_counter() - phase2_start
        logger.debug(f"  ⏱️  Read preparation took: {phase2_time:.3f}s")
        
        # Phase 3: Submit all read operations
        logger.debug("  📤 Phase 3: Submitting IO operations...")
        phase3_start = time.perf_counter()
        for resource in resources:
            self.submit_read(resource)
        phase3_time = time.perf_counter() - phase3_start
        logger.debug(f"  ⏱️  IO submission took: {phase3_time:.3f}s")
        
        # Phase 4: Wait for all completions
        logger.debug("  ⏳ Phase 4: Waiting for completions...")
        phase4_start = time.perf_counter()
        results = {}
        for i, resource in enumerate(resources):
            file_start_time = time.perf_counter()
            logger.debug(f"    📥 Waiting for file {i+1}/{len(resources)}: {os.path.basename(resource.file_path)}")
            
            try:
                total_read = self.wait_read(resource)
                file_load_time = time.perf_counter() - file_start_time
                logger.debug(f"    ⏱️  File {i+1} completion took: {file_load_time:.3f}s")
                
                # Success
                resource.load_time = file_load_time
                resource.success = True
                resource.error = None
                
                results[resource.file_path] = resource
                
            except Exception as e:
                file_load_time = time.perf_counter() - file_start_time
                logger.error(f"Read failed for {resource.file_path}: {e}")
                
                # Mark as failed and clean up completely
                resource.success = False
                resource.error = str(e)
                resource.load_time = file_load_time
                cleanup_usrbio_resource(resource)
                
                results[resource.file_path] = resource
        
        phase4_time = time.perf_counter() - phase4_start
        total_time = time.perf_counter() - start_time
        logger.debug(f"  ⏱️  Phase 4 (waiting) took: {phase4_time:.3f}s")
        logger.debug(f"🎯 Batch read completed in {total_time:.3f}s")
        logger.debug(f"   Phase breakdown: alloc={phase1_time:.1f}s, submit={phase2_time:.1f}s, io_submit={phase3_time:.1f}s, wait={phase4_time:.1f}s")
        
        return results

def _buffer_to_bytes(buffer):
    """Convert buffer (memoryview/shared memory) to bytes efficiently."""
    try:
        if hasattr(buffer, 'tobytes'):
            return buffer.tobytes()
        elif hasattr(buffer, 'raw'):
            return bytes(buffer.raw)
        else:
            return bytes(buffer)
    except Exception:
        # Fallback to simple bytes conversion
        return bytes(buffer)


def usrbio_save_state_dict(state_dict: Dict, output_dir: str, filename: str = "pytorch_model.bin", 
                          hf3fs_mount_point: str = None, block_size: int = USRBIO_DEFAULT_BLOCK_SIZE, 
                          chunk_size: int = USRBIO_DEFAULT_CHUNK_SIZE, priority: int = 0, use_safetensors: bool = False) -> Optional[FileWriteResult]:
    """
    Save model state_dict using usrbio for maximum performance.
    
    Args:
        state_dict: Model state dictionary to save
        output_dir: Directory to save the file
        filename: Name of the output file
        hf3fs_mount_point: Mount point for distributed filesystem
        priority: I/O priority (-1=HIGH, 0=NORMAL, 1=LOW)
        use_safetensors: Whether to use safetensors format instead of pickle
        
    Returns:
        FileWriteResult containing save statistics, or None if saving failed
    """
    if not USRBIO_AVAILABLE:
        logger.error("❌ USRBIO not available for state dict saving")
        return None
    
    if not TORCH_AVAILABLE:
        logger.error("❌ Torch not available for state dict saving")
        return None
    
    try:
        logger.info(f"🚀 USRBIO saving state_dict to {output_dir}/{filename}")
        
        # Ensure output directory exists
        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(output_dir, filename)
        
        # Determine mount point
        if hf3fs_mount_point is None:
            hf3fs_mount_point = extract_mount_point(output_dir)
        
        logger.debug(f"📁 Saving to: {output_path}")
        logger.debug(f"🚀 Using mount point: {hf3fs_mount_point}")
        
        # Serialize state dict to bytes
        serialization_start = time.perf_counter()
        if use_safetensors and safetensors:
            logger.debug("🔧 Serializing to safetensors format...")
            from io import BytesIO
            buffer = BytesIO()
            safetensors.torch.save(state_dict, buffer)
            file_data = buffer.getvalue()
            buffer.close()
        else:
            logger.debug("🔧 Serializing to PyTorch format...")
            from io import BytesIO
            buffer = BytesIO()
            torch.save(state_dict, buffer)
            file_data = buffer.getvalue()
            buffer.close()
        
        serialization_time = time.perf_counter() - serialization_start
        logger.debug(f"⏱️  Serialization took: {serialization_time:.3f}s")
        
        # Write using usrbio
        writer = UsrbioDirectWriter(
            hf3fs_mount_point=hf3fs_mount_point,
            block_size=block_size,
            chunk_size=chunk_size,
            priority=priority
        )
        
        write_result = writer.write_file(output_path, file_data)
        
        # Clean up
        del file_data
        
        if write_result.success:
            logger.success(f"✅ State dict saved successfully in {write_result.write_time:.3f}s")
            logger.debug(f"   Breakdown: serialization={serialization_time:.1f}s, write={write_result.write_time:.1f}s")
        else:
            logger.error(f"❌ Failed to save state dict: {write_result.error}")
        
        return write_result
        
    except Exception as e:
        logger.error(f"❌ USRBIO state dict saving failed: {e}")
        return None


def usrbio_save_pretrained(model, tokenizer=None, output_dir: str=None, 
                          hf3fs_mount_point: str = None, block_size: int = USRBIO_DEFAULT_BLOCK_SIZE, 
                          chunk_size: int = USRBIO_DEFAULT_CHUNK_SIZE, priority: int = 0, 
                          use_safetensors: bool = False, save_full_model: bool = True) -> Dict[str, FileWriteResult]:
    """
    Save model and tokenizer using usrbio acceleration with save_pretrained interface.
    
    This is the recommended way to use usrbio for saving models - it saves
    the model files using usrbio then falls back to standard methods for other files.
    
    Args:
        model: Model instance to save
        tokenizer: Optional tokenizer to save alongside the model
        output_dir: Directory to save the model
        hf3fs_mount_point: Mount point for distributed filesystem  
        priority: I/O priority (-1=HIGH, 0=NORMAL, 1=LOW)
        use_safetensors: Whether to use safetensors format
        save_full_model: Whether to save the full model or just state dict
        
    Returns:
        Dictionary of FileWriteResult objects for each file saved via USRBIO
    """
    logger.info(f"🚀 USRBIO save_pretrained: {output_dir}")
    
    if not USRBIO_AVAILABLE:
        logger.error("❌ USRBIO not available, falling back to standard save_pretrained")
        if hasattr(model, 'save_pretrained'):
            model.save_pretrained(output_dir)
        if tokenizer and hasattr(tokenizer, 'save_pretrained'):
            tokenizer.save_pretrained(output_dir)
        return {}
    
    # Ensure output directory exists
    os.makedirs(output_dir, exist_ok=True)
    
    # Determine mount point
    if hf3fs_mount_point is None:
        hf3fs_mount_point = extract_mount_point(output_dir)
    
    start_time = time.perf_counter()
    usrbio_results = {}
    
    try:
        logger.debug("🔧 Preparing model components for USRBIO saving...")
        
        # Create writer
        writer = UsrbioDirectWriter(
            hf3fs_mount_point=hf3fs_mount_point,
            block_size=block_size,
            chunk_size=chunk_size,
            priority=priority
        )
        
        # Prepare files to write via USRBIO
        files_to_write = {}
        
        # 1. Save model state dict
        if hasattr(model, 'state_dict'):
            logger.debug("📦 Preparing model state dict...")
            state_dict = model.state_dict()
            
            if use_safetensors and safetensors:
                model_filename = "model.safetensors"
                logger.debug("🔧 Serializing model to safetensors...")
                from io import BytesIO
                buffer = BytesIO()
                safetensors.torch.save(state_dict, buffer)
                model_data = buffer.getvalue()
                buffer.close()
            else:
                model_filename = "pytorch_model.bin"
                logger.debug("🔧 Serializing model to PyTorch format...")
                from io import BytesIO
                buffer = BytesIO()
                torch.save(state_dict, buffer)
                model_data = buffer.getvalue()
                buffer.close()
            
            files_to_write[os.path.join(output_dir, model_filename)] = model_data
        
        # 2. Save config
        if hasattr(model, 'config'):
            logger.debug("📦 Preparing model config...")
            config_data = json.dumps(model.config.to_dict(), indent=2).encode('utf-8')
            files_to_write[os.path.join(output_dir, "config.json")] = config_data
        
        # 3. Save tokenizer config if provided
        if tokenizer:
            logger.debug("📦 Preparing tokenizer config...")
            if hasattr(tokenizer, 'to_dict'):
                tokenizer_config = json.dumps(tokenizer.to_dict(), indent=2).encode('utf-8')
                files_to_write[os.path.join(output_dir, "tokenizer_config.json")] = tokenizer_config
        
        # Write all files using USRBIO
        if files_to_write:
            logger.debug(f"🚀 Writing {len(files_to_write)} files using USRBIO...")
            usrbio_results = writer.write_files(files_to_write)
        
        # Use standard save_pretrained for other files (vocab, special tokens, etc.)
        logger.debug("📁 Using standard save for remaining files...")
        try:
            if tokenizer and hasattr(tokenizer, 'save_pretrained'):
                tokenizer.save_pretrained(output_dir)
        except Exception as e:
            logger.warning(f"⚠️  Standard tokenizer save failed: {e}")
        
        # Save additional model files that weren't covered by USRBIO
        try:
            if hasattr(model, 'save_pretrained'):
                # Temporarily skip files we already saved with USRBIO
                model.save_pretrained(output_dir)
        except Exception as e:
            logger.warning(f"⚠️  Standard model save failed: {e}")
        
        total_time = time.perf_counter() - start_time
        
        # Report results
        successful_usrbio_files = [r for r in usrbio_results.values() if r.success]
        if successful_usrbio_files:
            total_usrbio_time = sum(r.write_time for r in successful_usrbio_files)
            avg_throughput = sum(r.throughput_gbps for r in successful_usrbio_files) / len(successful_usrbio_files)
            
            logger.success(f"✅ USRBIO save_pretrained completed in {total_time:.3f}s")
            logger.debug(f"   USRBIO files: {len(successful_usrbio_files)}")
            logger.debug(f"   USRBIO write time: {total_usrbio_time:.3f}s")
            logger.debug(f"   Average throughput: {avg_throughput:.2f} GB/s")
        
        return usrbio_results
        
    except Exception as e:
        logger.error(f"❌ USRBIO save_pretrained failed: {e}")
        # Fallback to standard approach
        logger.warning("📁 Falling back to standard save_pretrained")
        try:
            if hasattr(model, 'save_pretrained'):
                model.save_pretrained(output_dir)
            if tokenizer and hasattr(tokenizer, 'save_pretrained'):
                tokenizer.save_pretrained(output_dir)
        except Exception as fallback_error:
            logger.error(f"❌ Fallback save_pretrained also failed: {fallback_error}")
        
        return usrbio_results

def cleanup_usrbio_results(results):
    """
    Clean up USRBIO results (legacy function for backward compatibility).
    
    For new code, use cleanup_usrbio_resource() or UsrbioDirectLoader.deallocate().
    """
    if isinstance(results, dict):
        # Handle dictionary of results
        for result in results.values():
            cleanup_usrbio_resource(result)
    elif isinstance(results, list):
        # Handle list of results
        for result in results:
            cleanup_usrbio_resource(result)
    else:
        # Handle single result
        cleanup_usrbio_resource(results)

def _load_safetensors_from_buffer(buffer):
    """Load safetensors directly from buffer without copying to bytes."""
    # Try direct buffer access first (zero-copy)
    try:
        if hasattr(buffer, 'tobytes'):
            # Use BytesIO to avoid full copy if possible
            from io import BytesIO
            # Create BytesIO from buffer - this should be more efficient than tobytes()
            bio = BytesIO(buffer)
            return safetensors.torch.load(bio.getvalue())
        else:
            return safetensors.torch.load(bytes(buffer))
    except Exception:
        # Fallback to bytes conversion
        file_data = _buffer_to_bytes(buffer)
        result = safetensors.torch.load(file_data)
        del file_data  # Clean up immediately
        return result

def usrbio_load_state_dict(model_name_or_path: str, cache_dir: str = None, 
                          hf3fs_mount_point: str = None, block_size: int = USRBIO_DEFAULT_BLOCK_SIZE,
                          chunk_size: int = USRBIO_DEFAULT_CHUNK_SIZE, priority: int = 0, max_concurrent: int = 8, 
                          prefer_safe: bool = True, use_streaming: bool = True) -> Tuple[Optional[Dict], List[AllocationResource], Optional['UsrbioDirectLoader']]:
    """
    Load model state_dict using usrbio for maximum performance.
    
    Returns a state_dict that can be passed to from_pretrained(state_dict=...).
    This is the cleanest way to integrate usrbio with transformers.
    
    Args:
        model_name_or_path: Model name or path
        cache_dir: Cache directory for transformers
        hf3fs_mount_point: Mount point for distributed filesystem
        block_size: Block size for usrbio operations
        priority: I/O priority (-1=HIGH, 0=NORMAL, 1=LOW)
        max_concurrent: Maximum concurrent file operations
        prefer_safe: Whether to prefer safetensors over pytorch files
        use_streaming: Whether to use streaming approach (load one shard at a time)
                      vs batch approach (load all shards then process)
        
    Returns:
        Tuple of (state_dict, resources_list, loader) for manual cleanup
    """
    if not USRBIO_AVAILABLE:
        logger.error("❌ USRBIO not available for state dict loading")
        return None, [], None
    
    logger.info(f"🚀 USRBIO loading state_dict for {model_name_or_path}")
    
    # Track resources for cleanup
    all_resources = []
    loader = None
    
    # Determine model directory
    if os.path.isdir(model_name_or_path):
        model_dir = model_name_or_path
    else:
        # Standard HF cache path
        if cache_dir:
            model_dir = os.path.join(cache_dir, f"models--{model_name_or_path.replace('/', '--')}", "snapshots")
            # Find the snapshot directory
            if os.path.exists(model_dir):
                snapshot_dirs = [d for d in os.listdir(model_dir) if os.path.isdir(os.path.join(model_dir, d))]
                if snapshot_dirs:
                    model_dir = os.path.join(model_dir, snapshot_dirs[0])
                else:
                    logger.warning(f"⚠️  No snapshot directory found in {model_dir}")
                    return None
            else:
                logger.warning(f"⚠️  Model directory not found: {model_dir}")
                return None
        else:
            logger.warning(f"⚠️  cache_dir required for model name: {model_name_or_path}")
            return None
    
    # Determine mount point
    if hf3fs_mount_point is None:
        hf3fs_mount_point = extract_mount_point(model_dir)
    
    logger.debug(f"📁 Loading from: {model_dir}")
    
    # Check for index files to determine if sharded
    index_file = os.path.join(model_dir, "pytorch_model.bin.index.json")
    safe_index_file = os.path.join(model_dir, "model.safetensors.index.json")
    
    index_present = os.path.isfile(index_file)
    safe_index_present = os.path.isfile(safe_index_file)
    
    if index_present or safe_index_present:
        # Sharded model - use comprehensive loading
        logger.debug(f"📋 Detected sharded model")
        
        load_safe = False
        if safe_index_present:
            if prefer_safe:
                load_safe = True
            elif not index_present:
                load_safe = True
        
        load_index = safe_index_file if load_safe else index_file
        
        with open(load_index, "r", encoding="utf-8") as f:
            index = json.load(f)
        
        shard_files = list(set(index["weight_map"].values()))
        shard_paths = [os.path.join(model_dir, shard_file) for shard_file in shard_files]
        
        logger.debug(f"📋 Found {len(shard_files)} shard files to load")
        
        # Load all shard files using direct usrbio
        loader = UsrbioDirectLoader(
            hf3fs_mount_point=hf3fs_mount_point,
            block_size=block_size,
            chunk_size=chunk_size,
            priority=priority
        )
        
        if use_streaming:
            # STREAMING APPROACH: Load and process shards one at a time (memory efficient)
            logger.debug(f"🚀 Using streaming approach for {len(shard_files)} shards...")
            combine_start = time.perf_counter()
            
            combined_state_dict = {}
            total_file_load_time = 0
            total_parse_time = 0
            
            for i, shard_file in enumerate(shard_files):
                shard_path = os.path.join(model_dir, shard_file)
                shard_start = time.perf_counter()
                logger.debug(f"  🔧 Streaming shard {i+1}/{len(shard_files)}: {shard_file}")
                
                # Parse shard data - try direct file loading first (bypass USRBIO for parsing)
                parse_start = time.perf_counter()
                if load_safe:
                    try:
                        # Use file path directly if possible (most efficient, bypasses USRBIO for parsing)
                        shard_state_dict = safetensors.torch.load_file(shard_path, device="cpu")
                        parse_time = time.perf_counter() - parse_start
                        logger.debug(f"    ✅ Direct file loading took: {parse_time:.3f}s")
                        total_parse_time += parse_time
                        
                        # Skip USRBIO loading entirely for this shard
                        use_usrbio_for_shard = False
                    except Exception as e:
                        logger.debug(f"    ⚠️  Direct file loading failed ({e}), using USRBIO")
                        use_usrbio_for_shard = True
                else:
                    use_usrbio_for_shard = True
                
                if use_usrbio_for_shard:
                    # Load single shard file with USRBIO
                    file_load_start = time.perf_counter()
                    resource = loader.read_file(shard_path)
                    file_load_time = time.perf_counter() - file_load_start
                    total_file_load_time += file_load_time
                    logger.debug(f"    📥 USRBIO file load took: {file_load_time:.3f}s")
                    
                    if not resource.success:
                        logger.error(f"    ❌ Failed to load {shard_file}: {resource.error}")
                        continue
                    
                    # Parse shard data from buffer
                    parse_start = time.perf_counter()
                    if load_safe:
                        file_data = _buffer_to_bytes(resource.buffer)
                        shard_state_dict = safetensors.torch.load(file_data)
                        del file_data
                    else:
                        file_data = _buffer_to_bytes(resource.buffer)
                        shard_state_dict = torch.load(BytesIO(file_data), map_location="cpu", weights_only=True)
                        del file_data
                    
                    parse_time = time.perf_counter() - parse_start
                    total_parse_time += parse_time
                    logger.debug(f"    🔧 USRBIO parse took: {parse_time:.3f}s")
                    
                # Find which keys belong to this shard and add them
                shard_keys = [k for k, v in index['weight_map'].items() if v == shard_file]
                logger.debug(f"    📋 Adding {len(shard_keys)} keys from {len(shard_state_dict)} tensors")
                
                keys_added = 0
                for key in shard_keys:
                    if key in shard_state_dict:
                        combined_state_dict[key] = shard_state_dict[key]
                        keys_added += 1
                
                logger.debug(f"    ✅ Added {keys_added} tensors")
                
                # Clean up shard state dict and track USRBIO resource
                del shard_state_dict
                if use_usrbio_for_shard:
                    # Track USRBIO resource for later cleanup
                    all_resources.append(resource)
                gc.collect()
                
                shard_time = time.perf_counter() - shard_start
                logger.debug(f"    ⏱️  Shard {i+1} total time: {shard_time:.3f}s")
            
            combine_time = time.perf_counter() - combine_start
            logger.debug(f"⏱️  Streaming combine took: {combine_time:.3f}s")
            logger.debug(f"    Breakdown: usrbio_load={total_file_load_time:.1f}s, parse={total_parse_time:.1f}s")
            
        else:
            # BATCH APPROACH: Load all files then process (original approach)
            logger.debug(f"🔧 Using batch approach for {len(shard_files)} shards...")
            
            # Batch load all shard files
            file_load_start = time.perf_counter()
            shard_data = loader.read_files(shard_paths)
            file_load_time = time.perf_counter() - file_load_start
            logger.debug(f"⏱️  Batch file loading took: {file_load_time:.3f}s")
            
            # Combine shards into unified state_dict
            logger.debug(f"🔧 Combining {len(shard_data)} shards into unified state dict...")
            combine_start = time.perf_counter()
            
            combined_state_dict = {}
            
            for i, shard_file in enumerate(shard_files):
                if shard_file in shard_data:
                    shard_start = time.perf_counter()
                    logger.debug(f"  🔧 Processing shard {i+1}/{len(shard_files)}: {shard_file}")
                    
                    resource = shard_data[shard_file]
                    
                    # Parse shard data from buffer
                    if load_safe:
                        file_data = _buffer_to_bytes(resource.buffer)
                        shard_state_dict = safetensors.torch.load(file_data)
                        del file_data
                    else:
                        shard_state_dict = torch.UntypedStorage.from_buffer(resource.buffer, dtype=torch.int8, count=len(resource.buffer), offset=0)
                    
                    # Find which keys belong to this shard
                    shard_keys = [k for k, v in index['weight_map'].items() if v == shard_file]
                    logger.debug(f"    📋 Shard has {len(shard_keys)} keys, state_dict has {len(shard_state_dict)} tensors")
                    
                    for key in shard_keys:
                        if key in shard_state_dict:
                            combined_state_dict[key] = shard_state_dict[key]
                    
                    del shard_state_dict
                    
                    # Track USRBIO resource for later cleanup
                    all_resources.append(resource)
                    
                    gc.collect()
                    
                    shard_time = time.perf_counter() - shard_start
                    logger.debug(f"    ⏱️  Shard {i+1} processing took: {shard_time:.3f}s")
            
            combine_time = time.perf_counter() - combine_start
            logger.debug(f"⏱️  Batch combining took: {combine_time:.3f}s")
            
        
        logger.success(f"✅ Combined state dict with {len(combined_state_dict)} parameters")
        return combined_state_dict, all_resources, loader
        
    else:
        # Single file model
        safetensors_file = os.path.join(model_dir, "model.safetensors")
        pytorch_file = os.path.join(model_dir, "pytorch_model.bin")
        
        target_file = None
        use_safetensors = False
        
        if os.path.exists(safetensors_file) and (prefer_safe or not os.path.exists(pytorch_file)):
            target_file = safetensors_file
            use_safetensors = True
        elif os.path.exists(pytorch_file):
            target_file = pytorch_file
            use_safetensors = False
        else:
            logger.warning(f"⚠️  No model files found in {model_dir}")
            return None
        
        logger.debug(f"📄 Loading single file: {os.path.basename(target_file)}")
        
        # Load single file using direct usrbio
        loader = UsrbioDirectLoader(
            hf3fs_mount_point=hf3fs_mount_point,
            block_size=block_size,
            chunk_size=chunk_size,
            priority=priority
        )
        
        single_file_start = time.perf_counter()
        resource = loader.read_file(target_file)
        file_read_time = time.perf_counter() - single_file_start
        logger.debug(f"⏱️  Single file read took: {file_read_time:.3f}s")
        
        # Convert memoryview to bytes for safetensors/torch compatibility
        conversion_start = time.perf_counter()
        file_data = _buffer_to_bytes(resource.buffer)
        conversion_time = time.perf_counter() - conversion_start
        logger.debug(f"⏱️  Buffer conversion took: {conversion_time:.3f}s")
        
        # Parse the loaded data
        parse_start = time.perf_counter()
        if use_safetensors:
            logger.debug("  🔧 Parsing safetensors data...")
            state_dict = safetensors.torch.load(file_data)
        else:
            logger.debug("  🔧 Parsing torch data...")
            state_dict = torch.load(BytesIO(file_data), map_location="cpu", weights_only=True)
        parse_time = time.perf_counter() - parse_start
        logger.debug(f"⏱️  Data parsing took: {parse_time:.3f}s")
        
        # Clean up the file data copy and track USRBIO resource
        cleanup_start = time.perf_counter()
        del file_data
        
        # Track USRBIO resource for later cleanup
        all_resources.append(resource)
        
        cleanup_time = time.perf_counter() - cleanup_start
        logger.debug(f"⏱️  Resource tracking took: {cleanup_time:.3f}s")
        
        logger.success(f"✅ Loaded state dict with {len(state_dict)} parameters")
        return state_dict, all_resources, loader


def usrbio_from_pretrained(model_name_or_path: str, cache_dir: str = None,
                          hf3fs_mount_point: str = None, block_size: int = USRBIO_DEFAULT_BLOCK_SIZE,
                          chunk_size: int = USRBIO_DEFAULT_CHUNK_SIZE, priority: int = 0, max_concurrent: int = 8, use_streaming: bool = False, 
                          **kwargs) -> ModelWithResources:
    """
    Load model using usrbio acceleration with from_pretrained interface.
    
    This is the recommended way to use usrbio with transformers - it loads
    the state_dict using usrbio then passes it to from_pretrained.
    
    Args:
        model_name_or_path: Model name or path
        cache_dir: Cache directory for transformers
        hf3fs_mount_point: Mount point for distributed filesystem  
        block_size: Block size for usrbio operations
        priority: I/O priority (-1=HIGH, 0=NORMAL, 1=LOW)
        max_concurrent: Maximum concurrent file operations
        use_streaming: Whether to use streaming approach (load one shard at a time)
        **kwargs: Additional arguments passed to from_pretrained
        
    Returns:
        ModelWithResources containing model and resources for manual cleanup
    """
    logger.info(f"🚀 USRBIO from_pretrained: {model_name_or_path}")
    
    # Load state_dict using usrbio
    start_time = time.perf_counter()
    state_dict, resources, loader = usrbio_load_state_dict(
        model_name_or_path=model_name_or_path,
        cache_dir=cache_dir,
        hf3fs_mount_point=hf3fs_mount_point,
        block_size=block_size,
        chunk_size=chunk_size,
        priority=priority,
        max_concurrent=max_concurrent,
        use_streaming=use_streaming
    )
    if state_dict is None:
        logger.error("⚠️  USRBIO loading failed, no state dict returned")
        return ModelWithResources(model=None, resources=[], loader=None)
    
    state_dict_time = time.perf_counter() - start_time
    logger.debug(f"⏱️  State dict loading took: {state_dict_time:.3f}s")
    # Load config and create model from config only, then load state_dict
    logger.success("✅ Using usrbio-loaded state_dict with config-based model creation")
    
    # Load config first
    logger.debug("🔧 Loading model config...")
    config_start = time.perf_counter()
    config = AutoConfig.from_pretrained(model_name_or_path, cache_dir=cache_dir)
    config_time = time.perf_counter() - config_start
    if hasattr(config, "quantization_config"):
        delattr(config, "quantization_config")
    logger.debug(f"⏱️  Config loading took: {config_time:.3f}s")
    
    # Create model from config only (no weights loaded)
    logger.debug("🏗️  Creating model from config (no weights)...")
    model_creation_start = time.perf_counter()
    model = PreTrainedModel.from_pretrained(pretrained_model_name_or_path=None, config=config, state_dict=state_dict, **kwargs)
    model_creation_time = time.perf_counter() - model_creation_start
    logger.debug(f"⏱️  Model creation took: {model_creation_time:.3f}s")
    
    total_time = time.perf_counter() - start_time
    logger.success(f"✅ USRBIO from_pretrained completed in {total_time:.3f}s")
    logger.debug(f"   Breakdown: state_dict={state_dict_time:.1f}s, config={config_time:.1f}s, model_creation={model_creation_time:.1f}s")
    
    # Return ModelWithResources for explicit resource management
    return ModelWithResources(
        model=model,
        resources=resources,  # Resources that need cleanup
        loader=loader         # Loader for resource cleanup
    )


# Global state for hooks
_original_safe_load_file = None
_original_torch_load = None
_usrbio_enabled = False
_usrbio_config = {}


def install_usrbio_hooks(hf3fs_mount_point=None, block_size=USRBIO_DEFAULT_BLOCK_SIZE, chunk_size=USRBIO_DEFAULT_CHUNK_SIZE, priority=0, max_concurrent=4):
    """Install hooks to replace safe_load_file and torch.load with usrbio versions."""
    global _original_safe_load_file, _original_torch_load, _usrbio_enabled, _usrbio_config
    
    if not USRBIO_AVAILABLE:
        logger.warning("⚠️  Cannot install usrbio hooks - usrbio not available")
        return False
    
    _usrbio_config = {
        'hf3fs_mount_point': hf3fs_mount_point,
        'block_size': block_size,
        'chunk_size': chunk_size,
        'priority': priority,
        'max_concurrent': max_concurrent
    }
    
    # Store original functions for cleanup
    _original_safe_open = None
    
    try:
        # Hook safetensors.torch.load_file (this is what transformers uses as safe_load_file)
        from safetensors.torch import load_file as original_load_file
        _original_safe_load_file = original_load_file
        
        def usrbio_safe_load_file(filename, device="cpu"):
            """Usrbio-accelerated version of safetensors.torch.load_file."""
            logger.debug(f"🚀 USRBIO safetensors.torch.load_file: {Path(filename).name}")
            
            # Determine mount point
            mount_point = _usrbio_config['hf3fs_mount_point']
            if mount_point is None:
                mount_point = extract_mount_point(str(filename))
            
            # Use direct usrbio loader
            loader = UsrbioDirectLoader(
                hf3fs_mount_point=mount_point,
                block_size=_usrbio_config['block_size'],
                chunk_size=_usrbio_config['chunk_size'],
                priority=_usrbio_config['priority']
            )
            
            resource = loader.read_file(str(filename))
            
            if not resource.success: # Check for 'success' key
                logger.warning(f"⚠️  USRBIO failed, falling back to original")
                return _original_safe_load_file(filename, device=device)
            
            # Convert memoryview to bytes for safetensors compatibility
            file_data = _buffer_to_bytes(resource.buffer)
            
            # Load using safetensors from memory
            result = safetensors.torch.load(file_data)
            
            # Clean up
            del file_data
            loader.deallocate(resource)
            
            logger.success(f"✅ USRBIO safetensors.torch.load_file completed: {resource.file_size / (1024**3) / resource.load_time:.2f} GB/s")
            return result
        
        # Replace the function in the torch module
        import safetensors.torch
        safetensors.torch.load_file = usrbio_safe_load_file
        logger.debug("🔗 HOOK INSTALLED: safetensors.torch.load_file")
        
    except ImportError:
        logger.warning("⚠️  Could not hook safetensors.torch.load_file")
    
    try:
        # Hook safetensors.safe_open (also used by transformers)
        from safetensors import safe_open as original_safe_open
        _original_safe_open = original_safe_open
        
        def usrbio_safe_open(filename, framework="torch", device="cpu"):
            """Usrbio-accelerated version of safetensors.safe_open."""
            logger.debug(f"🚀 USRBIO safetensors.safe_open: {Path(filename).name}")
            
            # For safe_open, we'll let it use the normal path since it's more complex
            # and returns a special safe_open context manager, not just tensors
            return _original_safe_open(filename, framework=framework, device=device)
        
        # Replace the function in the safetensors module
        import safetensors
        safetensors.safe_open = usrbio_safe_open
        logger.debug("🔗 HOOK INSTALLED: safetensors.safe_open")
        
    except ImportError:
        logger.warning("⚠️  Could not hook safetensors.safe_open")
    
    try:
        # Hook torch.load
        import torch
        _original_torch_load = torch.load
        
        def usrbio_torch_load(f, map_location=None, pickle_module=None, weights_only=False, **kwargs):
            """Usrbio-accelerated version of torch.load."""
            # Only hook file loads, not other objects
            if isinstance(f, (str, os.PathLike)):
                logger.debug(f"🚀 USRBIO torch.load: {Path(f).name}")
                
                # Determine mount point  
                mount_point = _usrbio_config['hf3fs_mount_point']
                if mount_point is None:
                    mount_point = extract_mount_point(str(f))
                
                # Use direct usrbio loader
                loader = UsrbioDirectLoader(
                    hf3fs_mount_point=mount_point,
                    block_size=_usrbio_config['block_size'],
                    chunk_size=_usrbio_config['chunk_size'],
                    priority=_usrbio_config['priority']
                )
                
                resource = loader.read_file(str(f))
                
                if not resource.success: # Check for 'success' key
                    logger.warning(f"⚠️  USRBIO failed, falling back to original")
                    return _original_torch_load(f, map_location=map_location, 
                                              pickle_module=pickle_module, 
                                              weights_only=weights_only, **kwargs)
                
                # Convert memoryview to bytes for torch compatibility
                file_data = _buffer_to_bytes(resource.buffer)
                
                # Load using torch from memory
                from io import BytesIO
                result = _original_torch_load(BytesIO(file_data), map_location=map_location,
                                            pickle_module=pickle_module, 
                                            weights_only=weights_only, **kwargs)
                
                # Clean up
                del file_data
                loader.deallocate(resource)
                
                logger.success(f"✅ USRBIO torch.load completed: {resource.file_size / (1024**3) / resource.load_time:.2f} GB/s")
                return result
            else:
                # Not a file, use original function
                return _original_torch_load(f, map_location=map_location,
                                          pickle_module=pickle_module,
                                          weights_only=weights_only, **kwargs)
        
        # Replace the function
        torch.load = usrbio_torch_load
        logger.debug("🔗 HOOK INSTALLED: torch.load")
        
    except ImportError:
        logger.warning("⚠️  Could not hook torch.load")
    
    _usrbio_enabled = True
    logger.info(f"🚀 USRBIO hooks installed successfully!")
    logger.debug(f"   Mount point: {_usrbio_config['hf3fs_mount_point']}")
    logger.debug(f"   Block size: {_usrbio_config['block_size']}")
    logger.debug(f"   Priority: {_usrbio_config['priority']}")
    
    return True


def remove_usrbio_hooks():
    """Remove usrbio hooks and restore original functions."""
    global _original_safe_load_file, _original_torch_load, _usrbio_enabled
    
    if not _usrbio_enabled:
        return
    
    try:
        if _original_safe_load_file:
            import safetensors.torch
            safetensors.torch.load_file = _original_safe_load_file
            logger.debug("🔓 HOOK REMOVED: safetensors.torch.load_file")
    except:
        pass
    
    try:
        if _original_torch_load:
            import torch
            torch.load = _original_torch_load
            logger.debug("🔓 HOOK REMOVED: torch.load")
    except:
        pass
    
    _usrbio_enabled = False
    logger.info("🔓 USRBIO hooks removed")


def benchmark_usrbio_vs_standard(file_paths: List[str], hf3fs_mount_point=None, 
                                 block_size: int = USRBIO_DEFAULT_BLOCK_SIZE, chunk_size: int = USRBIO_DEFAULT_CHUNK_SIZE, 
                                 runs=1, include_ssd=False, ssd_dir="/tmp/ssd_test") -> Dict:
    """Benchmark usrbio vs standard loading for given files."""
    if not USRBIO_AVAILABLE:
        logger.error("❌ USRBIO not available for benchmarking")
        return {}
    
    results = {'usrbio': [], 'standard': [], 'ssd': []}
    
    # Determine mount point
    if hf3fs_mount_point is None and file_paths:
        hf3fs_mount_point = extract_mount_point(str(file_paths[0]))
    
    loader = UsrbioDirectLoader(
        hf3fs_mount_point=hf3fs_mount_point,
        block_size=block_size,
        chunk_size=chunk_size,
        priority=0
    )
    
    # Prepare SSD copies if requested
    ssd_file_paths = []
    if include_ssd:
        ssd_file_paths = [f.replace('/3fs/stage/fuse/hf', '/ssd/hf') for f in file_paths]

    logger.info(f"🏁 Benchmarking {len(file_paths)} files over {runs} runs" + 
                (f" (with SSD comparison)" if include_ssd else ""))
    
    for run in range(runs):
        logger.info(f"\n--- Run {run + 1}/{runs} ---")
        
        # Benchmark USRBIO
        logger.debug("🚀 Testing USRBIO:")
        start_time = time.perf_counter()
        usrbio_resources = loader.read_files(file_paths)
        usrbio_time = time.perf_counter() - start_time
        
        try:
            usrbio_size = sum(resource.file_size for resource in usrbio_resources.values())
            results['usrbio'].append({
                'time': usrbio_time,
                'size': usrbio_size,
                'throughput_gbps': (usrbio_size / (1024**3)) / usrbio_time
            })
        finally:
            # Clean up all allocated resources
            for resource in usrbio_resources.values():
                loader.deallocate(resource)
        
        # Benchmark standard I/O
        logger.debug("📁 Testing Standard I/O:")
        start_time = time.perf_counter()
        standard_size = 0
        for file_path in file_paths:
            with open(file_path, 'rb') as f:
                data = f.read()
                standard_size += len(data)
                del data
        standard_time = time.perf_counter() - start_time
        
        results['standard'].append({
            'time': standard_time,
            'size': standard_size,
            'throughput_gbps': (standard_size / (1024**3)) / standard_time
        })
        
        speedup = standard_time / usrbio_time
        logger.info(f"⚡ USRBIO {speedup:.2f}x faster than standard this run")
        
        # Benchmark SSD if requested
        if include_ssd:
            logger.debug("💾 Testing SSD I/O:")
            start_time = time.perf_counter()
            ssd_size = 0
            for ssd_file_path in ssd_file_paths:
                with open(ssd_file_path, 'rb') as f:
                    data = f.read()
                    ssd_size += len(data)
                    del data
            ssd_time = time.perf_counter() - start_time
            
            results['ssd'].append({
                'time': ssd_time,
                'size': ssd_size,
                'throughput_gbps': (ssd_size / (1024**3)) / ssd_time
            })
            
            ssd_vs_usrbio = ssd_time / usrbio_time
            logger.info(f"💾 SSD {ssd_vs_usrbio:.2f}x slower than USRBIO this run")
    
    # Calculate averages
    avg_usrbio = {
        'time': sum(r['time'] for r in results['usrbio']) / runs,
        'throughput_gbps': sum(r['throughput_gbps'] for r in results['usrbio']) / runs
    }
    
    avg_standard = {
        'time': sum(r['time'] for r in results['standard']) / runs,
        'throughput_gbps': sum(r['throughput_gbps'] for r in results['standard']) / runs
    }
    
    overall_speedup = avg_standard['time'] / avg_usrbio['time']
    throughput_improvement = avg_usrbio['throughput_gbps'] / avg_standard['throughput_gbps']
    
    if include_ssd:
        avg_ssd = {
            'time': sum(r['time'] for r in results['ssd']) / runs,
            'throughput_gbps': sum(r['throughput_gbps'] for r in results['ssd']) / runs
        }
        ssd_vs_usrbio_speedup = avg_ssd['time'] / avg_usrbio['time']
    
    logger.success(f"\n🎯 BENCHMARK RESULTS:")
    logger.info(f"   USRBIO: {avg_usrbio['time']:.3f}s avg ({avg_usrbio['throughput_gbps']:.2f} GB/s)")
    logger.info(f"   Standard: {avg_standard['time']:.3f}s avg ({avg_standard['throughput_gbps']:.2f} GB/s)")
    if include_ssd:
        logger.info(f"   SSD: {avg_ssd['time']:.3f}s avg ({avg_ssd['throughput_gbps']:.2f} GB/s)")
    logger.info(f"   USRBIO vs Standard speedup: {overall_speedup:.2f}x")
    if include_ssd:
        logger.info(f"   USRBIO vs SSD speedup: {ssd_vs_usrbio_speedup:.2f}x")
    logger.info(f"   Throughput improvement: {throughput_improvement:.2f}x")
    
    result_dict = {
        'usrbio': results['usrbio'],
        'standard': results['standard'],
        'averages': {
            'usrbio': avg_usrbio,
            'standard': avg_standard
        },
        'speedup': overall_speedup,
        'throughput_improvement': throughput_improvement
    }
    
    if include_ssd:
        result_dict['ssd'] = results['ssd']
        result_dict['averages']['ssd'] = avg_ssd
        result_dict['ssd_vs_usrbio_speedup'] = ssd_vs_usrbio_speedup
    
    return result_dict

def print_phase_analysis(analysis: Dict):
    """Print a formatted analysis of phase timing results."""
    if 'error' in analysis:
        logger.error(f"❌ Analysis error: {analysis['error']}")
        return
    
    logger.info(f"\n📊 ASYNC LOAD PHASE ANALYSIS")
    logger.info(f"   Files analyzed: {analysis['total_files']}")
    logger.info(f"   Total data: {analysis['total_size_gb']:.2f} GB")
    logger.info(f"   Average throughput: {analysis['avg_throughput_gbps']:.2f} GB/s")
    
    logger.info(f"\n⏱️  PHASE BREAKDOWN:")
    for phase, data in analysis['phase_analysis'].items():
        logger.info(f"   {phase.replace('_', ' ').title()}:")
        logger.info(f"      Average: {data['avg_time_ms']:.2f}ms ({data['avg_percentage']:.1f}%)")
        logger.info(f"      Range: {data['min_time_ms']:.2f}-{data['max_time_ms']:.2f}ms")
        logger.info(f"      Std dev: {data['std_deviation_ms']:.2f}ms")
    
    if analysis.get('bottlenecks'):
        logger.warning(f"\n🚨 IDENTIFIED BOTTLENECKS:")
        for i, bottleneck in enumerate(analysis['bottlenecks'], 1):
            logger.warning(f"   {i}. {bottleneck['phase'].replace('_', ' ').title()}: {bottleneck['avg_percentage']:.1f}% ({bottleneck['avg_time_ms']:.2f}ms avg)")
        
        if analysis.get('primary_bottleneck'):
            primary = analysis['primary_bottleneck']
            logger.error(f"\n🎯 PRIMARY BOTTLENECK: {primary['phase'].replace('_', ' ').title()} ({primary['avg_percentage']:.1f}%)")
            logger.info(f"   💡 Recommendation: {primary['recommendation']}")
    else:
        logger.success(f"\n✅ No significant bottlenecks detected (all phases <10%)")


def usrbio_save_checkpoint(checkpoint_data: Dict[str, Any], 
                          output_dir: str, 
                          checkpoint_name: str = "checkpoint",
                          hf3fs_mount_point: str = None, 
                          block_size: int = USRBIO_DEFAULT_BLOCK_SIZE,
                          chunk_size: int = USRBIO_DEFAULT_CHUNK_SIZE,
                          priority: int = 0, 
                          use_safetensors: bool = False,
                          compress: bool = False) -> Optional[FileWriteResult]:
    """
    Save a comprehensive training checkpoint using USRBIO for maximum performance.
    
    This function handles complete training checkpoints including model state, optimizer state,
    scheduler state, training metadata, and custom data.
    
    Args:
        checkpoint_data: Dictionary containing checkpoint components with keys like:
            - 'model_state_dict': Model state dictionary (required)
            - 'optimizer_state_dict': Optimizer state dictionary (optional)
            - 'scheduler_state_dict': Learning rate scheduler state (optional)
            - 'epoch': Current training epoch (optional)
            - 'step': Current training step (optional)
            - 'best_metric': Best metric achieved so far (optional)
            - 'loss': Current loss value (optional)
            - 'learning_rate': Current learning rate (optional)
            - 'random_states': Dictionary of random states for reproducibility (optional)
            - 'metadata': Custom metadata dictionary (optional)
            - Any other custom keys
        output_dir: Directory to save the checkpoint
        checkpoint_name: Base name for the checkpoint file (without extension)
        hf3fs_mount_point: Mount point for distributed filesystem
        priority: I/O priority (-1=HIGH, 0=NORMAL, 1=LOW)
        use_safetensors: Whether to use safetensors format (only for state dicts)
        compress: Whether to compress the checkpoint data
        
    Returns:
        FileWriteResult containing save statistics, or None if saving failed
        
    Example:
        checkpoint_data = {
            'model_state_dict': model.state_dict(),
            'optimizer_state_dict': optimizer.state_dict(),
            'scheduler_state_dict': scheduler.state_dict(),
            'epoch': 10,
            'step': 1000,
            'best_metric': 0.85,
            'loss': 0.23,
            'learning_rate': 1e-4,
            'random_states': {
                'python': random.getstate(),
                'numpy': np.random.get_state(), 
                'torch': torch.get_rng_state(),
                'torch_cuda': torch.cuda.get_rng_state_all() if torch.cuda.is_available() else None
            },
            'metadata': {
                'model_name': 'my-model',
                'dataset': 'my-dataset',
                'batch_size': 32,
                'created_by': 'training_script_v1.0'
            }
        }
        
        result = usrbio_save_checkpoint(
            checkpoint_data=checkpoint_data,
            output_dir="/path/to/checkpoints",
            checkpoint_name="checkpoint-epoch-10",
            use_safetensors=True
        )
    """
    if not USRBIO_AVAILABLE:
        logger.error("❌ USRBIO not available for checkpoint saving")
        return None
    
    if not TORCH_AVAILABLE:
        logger.error("❌ Torch not available for checkpoint saving")
        return None
    
    if not checkpoint_data:
        logger.error("❌ Empty checkpoint data provided")
        return None
    
    try:
        logger.info(f"🚀 USRBIO saving checkpoint '{checkpoint_name}' to {output_dir}")
        
        # Ensure output directory exists
        os.makedirs(output_dir, exist_ok=True)
        
        # Determine mount point
        if hf3fs_mount_point is None:
            hf3fs_mount_point = extract_mount_point(output_dir)
        
        # Validate checkpoint data
        if 'model_state_dict' not in checkpoint_data:
            logger.warning("⚠️  No 'model_state_dict' found in checkpoint data")
        
        # Log checkpoint contents
        components = []
        if 'model_state_dict' in checkpoint_data:
            components.append("model")
        if 'optimizer_state_dict' in checkpoint_data:
            components.append("optimizer")
        if 'scheduler_state_dict' in checkpoint_data:
            components.append("scheduler")
        if 'random_states' in checkpoint_data:
            components.append("random_states")
        if 'metadata' in checkpoint_data:
            components.append("metadata")
        
        # Add other keys that aren't state dicts
        other_keys = [k for k in checkpoint_data.keys() 
                     if k not in ['model_state_dict', 'optimizer_state_dict', 'scheduler_state_dict', 'random_states', 'metadata']]
        if other_keys:
            components.append(f"training_info({len(other_keys)})")
        
        logger.debug(f"📦 Checkpoint components: {', '.join(components)}")
        
        # Choose file format and extension
        if use_safetensors and safetensors:
            # For safetensors, we need to separate state dicts from other data
            # Save state dicts as safetensors and other data as separate file
            logger.debug("🔧 Using safetensors format for state dicts")
            
            # Extract state dictionaries
            state_dicts = {}
            other_data = {}
            
            for key, value in checkpoint_data.items():
                if key.endswith('_state_dict') and isinstance(value, dict):
                    # Flatten state dict keys to avoid nesting issues in safetensors
                    flattened_key = key.replace('_state_dict', '')
                    for subkey, tensor in value.items():
                        state_dicts[f"{flattened_key}.{subkey}"] = tensor
                else:
                    other_data[key] = value
            
            files_to_save = {}
            
            # Save state dicts as safetensors
            if state_dicts:
                safetensors_path = os.path.join(output_dir, f"{checkpoint_name}.safetensors")
                
                serialization_start = time.perf_counter()
                from io import BytesIO
                buffer = BytesIO()
                safetensors.torch.save(state_dicts, buffer)
                safetensors_data = buffer.getvalue()
                buffer.close()
                serialization_time = time.perf_counter() - serialization_start
                
                files_to_save[safetensors_path] = safetensors_data
                logger.debug(f"⏱️  Safetensors serialization took: {serialization_time:.3f}s")
            
            # Save other data as pickle
            if other_data:
                metadata_path = os.path.join(output_dir, f"{checkpoint_name}_metadata.pt")
                
                serialization_start = time.perf_counter()
                from io import BytesIO
                buffer = BytesIO()
                torch.save(other_data, buffer)
                metadata_data = buffer.getvalue()
                buffer.close()
                serialization_time = time.perf_counter() - serialization_start
                
                files_to_save[metadata_path] = metadata_data
                logger.debug(f"⏱️  Metadata serialization took: {serialization_time:.3f}s")
            
        else:
            # Standard PyTorch format - save everything in one file
            logger.debug("🔧 Using PyTorch format for complete checkpoint")
            
            file_extension = ".pt" if not compress else ".pt.gz"
            checkpoint_path = os.path.join(output_dir, f"{checkpoint_name}{file_extension}")
            
            serialization_start = time.perf_counter()
            from io import BytesIO
            buffer = BytesIO()
            
            if compress:
                import gzip
                # Serialize to bytes first, then compress
                torch.save(checkpoint_data, buffer)
                uncompressed_data = buffer.getvalue()
                buffer.close()
                
                # Compress the data
                compressed_data = gzip.compress(uncompressed_data)
                files_to_save = {checkpoint_path: compressed_data}
                logger.debug(f"🗜️  Compression ratio: {len(compressed_data)/len(uncompressed_data):.2f}")
            else:
                torch.save(checkpoint_data, buffer)
                checkpoint_file_data = buffer.getvalue()
                buffer.close()
                files_to_save = {checkpoint_path: checkpoint_file_data}
            
            serialization_time = time.perf_counter() - serialization_start
            logger.debug(f"⏱️  Checkpoint serialization took: {serialization_time:.3f}s")
        
        # Write files using USRBIO
        writer = UsrbioDirectWriter(
            hf3fs_mount_point=hf3fs_mount_point,
            block_size=block_size,
            chunk_size=chunk_size,
            priority=priority
        )
        
        if len(files_to_save) == 1:
            # Single file - use direct write
            file_path, file_data = next(iter(files_to_save.items()))
            write_result = writer.write_file(file_path, file_data)
            
            # Clean up
            del file_data
            
            if write_result.success:
                # Add checkpoint summary to result
                summary_info = {
                    'components': components,
                    'format': 'safetensors+metadata' if use_safetensors else 'pytorch',
                    'compressed': compress,
                    'total_components': len(checkpoint_data)
                }
                
                logger.success(f"✅ Checkpoint saved successfully in {write_result.write_time:.3f}s")
                logger.debug(f"   Format: {summary_info['format']}")
                logger.debug(f"   Components: {summary_info['components']}")
                logger.debug(f"   File size: {write_result.file_size / (1024**2):.1f}MB")
                logger.debug(f"   Throughput: {write_result.throughput_gbps:.2f} GB/s")
                
                # Add summary to the result object
                write_result.checkpoint_summary = summary_info
                
            return write_result
            
        else:
            # Multiple files - use batch write
            write_results = writer.write_files(files_to_save)
            
            # Clean up
            for file_data in files_to_save.values():
                del file_data
            
            # Combine results
            total_time = sum(r.write_time for r in write_results.values() if r.success)
            total_size = sum(r.file_size for r in write_results.values() if r.success)
            successful_files = [r for r in write_results.values() if r.success]
            
            if successful_files:
                avg_throughput = sum(r.throughput_gbps for r in successful_files) / len(successful_files)
                
                # Create combined result
                combined_result = FileWriteResult(
                    file_path=output_dir,
                    file_size=total_size,
                    success=len(successful_files) == len(write_results),
                    error=None if len(successful_files) == len(write_results) else "Some files failed",
                    write_time=total_time,
                    throughput_gbps=avg_throughput
                )
                
                summary_info = {
                    'components': components,
                    'format': 'safetensors+metadata',
                    'compressed': compress,
                    'total_components': len(checkpoint_data),
                    'files_written': len(successful_files),
                    'total_files': len(write_results)
                }
                
                logger.success(f"✅ Checkpoint saved successfully in {total_time:.3f}s ({len(successful_files)}/{len(write_results)} files)")
                logger.debug(f"   Format: {summary_info['format']}")
                logger.debug(f"   Components: {summary_info['components']}")
                logger.debug(f"   Total size: {total_size / (1024**2):.1f}MB")
                logger.debug(f"   Average throughput: {avg_throughput:.2f} GB/s")
                
                # Add summary to the result object
                combined_result.checkpoint_summary = summary_info
                combined_result.individual_results = write_results
                
                return combined_result
            else:
                logger.error("❌ All checkpoint file writes failed")
                return None
        
    except Exception as e:
        logger.error(f"❌ USRBIO checkpoint saving failed: {e}")
        import traceback
        logger.debug(f"Traceback: {traceback.format_exc()}")
        return None


def usrbio_load_checkpoint(checkpoint_path: str,
                          hf3fs_mount_point: str = None,
                          block_size: int = USRBIO_DEFAULT_BLOCK_SIZE,
                          chunk_size: int = USRBIO_DEFAULT_CHUNK_SIZE,
                          priority: int = 0,
                          map_location: str = "cpu") -> Optional[Dict[str, Any]]:
    """
    Load a checkpoint saved with usrbio_save_checkpoint.
    
    Args:
        checkpoint_path: Path to the checkpoint file or directory
        hf3fs_mount_point: Mount point for distributed filesystem
        priority: I/O priority (-1=HIGH, 0=NORMAL, 1=LOW)
        map_location: Device to map tensors to (e.g., 'cpu', 'cuda')
        
    Returns:
        Dictionary containing all checkpoint data, or None if loading failed
    """
    if not USRBIO_AVAILABLE:
        logger.error("❌ USRBIO not available for checkpoint loading")
        return None
    
    if not TORCH_AVAILABLE:
        logger.error("❌ Torch not available for checkpoint loading")
        return None
    
    try:
        logger.info(f"🚀 USRBIO loading checkpoint from {checkpoint_path}")
        
        # Determine mount point
        if hf3fs_mount_point is None:
            hf3fs_mount_point = extract_mount_point(checkpoint_path)
        
        # Check if path is a directory (safetensors + metadata) or single file
        if os.path.isdir(checkpoint_path):
            # Directory - look for safetensors and metadata files
            checkpoint_files = []
            for file in os.listdir(checkpoint_path):
                if file.endswith('.safetensors') or file.endswith('_metadata.pt'):
                    checkpoint_files.append(os.path.join(checkpoint_path, file))
            
            if not checkpoint_files:
                logger.error(f"❌ No checkpoint files found in directory: {checkpoint_path}")
                return None
                
            loader = UsrbioDirectLoader(
                hf3fs_mount_point=hf3fs_mount_point,
                block_size=block_size,
                chunk_size=chunk_size,
                priority=priority
            )
            
            # Load all files
            resources = loader.read_files(checkpoint_files)
            
            combined_data = {}
            
            for file_path, resource in resources.items():
                if not resource.success:
                    logger.error(f"❌ Failed to load {file_path}: {resource.error}")
                    continue
                
                file_data = _buffer_to_bytes(resource.buffer)
                
                if file_path.endswith('.safetensors'):
                    # Load safetensors state dicts
                    state_dicts = safetensors.torch.load(file_data)
                    
                    # Unflatten the keys back to original structure
                    model_state = {}
                    optimizer_state = {}
                    scheduler_state = {}
                    
                    for key, tensor in state_dicts.items():
                        if key.startswith('model.'):
                            model_state[key[6:]] = tensor  # Remove 'model.' prefix
                        elif key.startswith('optimizer.'):
                            optimizer_state[key[10:]] = tensor  # Remove 'optimizer.' prefix
                        elif key.startswith('scheduler.'):
                            scheduler_state[key[10:]] = tensor  # Remove 'scheduler.' prefix
                    
                    if model_state:
                        combined_data['model_state_dict'] = model_state
                    if optimizer_state:
                        combined_data['optimizer_state_dict'] = optimizer_state
                    if scheduler_state:
                        combined_data['scheduler_state_dict'] = scheduler_state
                        
                elif file_path.endswith('_metadata.pt'):
                    # Load metadata
                    from io import BytesIO
                    metadata = torch.load(BytesIO(file_data), map_location=map_location, weights_only=False)
                    combined_data.update(metadata)
                
                # Clean up
                del file_data
                
                # Clean up USRBIO resource
                loader.deallocate(resource)
            
            logger.success(f"✅ Checkpoint loaded successfully from {len(resources)} files")
            return combined_data
            
        else:
            # Single file
            if not os.path.exists(checkpoint_path):
                logger.error(f"❌ Checkpoint file not found: {checkpoint_path}")
                return None
            
            loader = UsrbioDirectLoader(
                hf3fs_mount_point=hf3fs_mount_point,
                block_size=block_size,
                chunk_size=chunk_size,
                priority=priority
            )
            
            resource = loader.read_file(checkpoint_path)
            
            if not resource.success:
                logger.error(f"❌ Failed to load checkpoint: {resource.error}")
                return None
            
            # Convert buffer to bytes
            file_data = _buffer_to_bytes(resource.buffer)
            
            # Load checkpoint
            if checkpoint_path.endswith('.pt.gz'):
                # Decompress first
                import gzip
                decompressed_data = gzip.decompress(file_data)
                from io import BytesIO
                checkpoint_data = torch.load(BytesIO(decompressed_data), map_location=map_location, weights_only=False)
            else:
                from io import BytesIO
                checkpoint_data = torch.load(BytesIO(file_data), map_location=map_location, weights_only=False)
            
            # Clean up
            del file_data
            
            # Clean up USRBIO resource
            loader.deallocate(resource)
            
            logger.success(f"✅ Checkpoint loaded successfully")
            logger.debug(f"   Components: {list(checkpoint_data.keys())}")
            
            return checkpoint_data
            
    except Exception as e:
        logger.error(f"❌ USRBIO checkpoint loading failed: {e}")
        import traceback
        logger.debug(f"Traceback: {traceback.format_exc()}")
        return None


if __name__ == "__main__":
    # Test file for detailed phase analysis
    file_paths = [
        "/3fs/stage/fuse/hf/models--deepseek-ai--DeepSeek-R1-Distill-Qwen-32B/snapshots/711ad2ea6aa40cfca18895e8aca02ab92df1a746/model-00005-of-000008.safetensors",
    ]

    logger.info("🧪 4-WAY PERFORMANCE COMPARISON: USRBIO vs Standard vs Torch vs SSD")
    logger.info("=" * 60)
    
    if not USRBIO_AVAILABLE:
        logger.error("❌ USRBIO not available")
        exit(1)
    
    # Create USRBIO loader
    mount_point = extract_mount_point(file_paths[0])
    loader_bytes = UsrbioDirectLoader(
        hf3fs_mount_point=mount_point,
        block_size=USRBIO_DEFAULT_BLOCK_SIZE,
        chunk_size=USRBIO_DEFAULT_CHUNK_SIZE,
        priority=0
    )
    
    # Prepare SSD file path
    ssd_file_path = file_paths[0].replace('/3fs/stage/fuse/hf', '/ssd/hf')
    
    # Test 1: USRBIO approach
    logger.info(f"\n🚀 USRBIO APPROACH (3 iterations)")
    logger.info("-" * 40)
    usrbio_stats = []
    usrbio_results = []
    iterations = 1
    
    for i in range(iterations):
        logger.info(f"\n--- USRBIO iteration {i+1}/{iterations} ---")
        start_time = time.perf_counter()
        resource = loader_bytes.read_file(file_paths[0])
        load_time = time.perf_counter() - start_time
        
        if resource.success:
            usrbio_stats.append({
                'time': load_time,
                'size': resource.file_size,
                'throughput_gbps': (resource.file_size / (1024**3)) / load_time
            })
            usrbio_results.append(resource)
        else:
            logger.error(f"❌ USRBIO load failed: {resource.error}")
    
    # Test 2: Standard I/O approach
    logger.info(f"\n📁 STANDARD I/O APPROACH (3 iterations)")
    logger.info("-" * 40)
    standard_stats = []
    
    for i in range(iterations):
        logger.info(f"\n--- Standard I/O iteration {i+1}/{iterations} ---")
        start_time = time.perf_counter()
        try:
            with open(file_paths[0], 'rb') as f:
                data = f.read()
                file_size = len(data)
                del data  # Clean up immediately
            load_time = time.perf_counter() - start_time
            
            standard_stats.append({
                'time': load_time,
                'size': file_size,
                'throughput_gbps': (file_size / (1024**3)) / load_time
            })
        except Exception as e:
            logger.error(f"❌ Standard I/O load failed: {e}")
    
    # Test 3: Torch loading approach
    logger.info(f"\n🔥 TORCH LOAD APPROACH (3 iterations)")
    logger.info("-" * 40)
    torch_stats = []
    
    if TORCH_AVAILABLE:
        for i in range(iterations):
            logger.info(f"\n--- Torch load iteration {i+1}/{iterations} ---")
            start_time = time.perf_counter()
            try:
                # Load using safetensors for .safetensors files, torch.load for .bin files
                if file_paths[0].endswith('.safetensors'):
                    data = safetensors.torch.load_file(file_paths[0], device="cpu")
                else:
                    data = torch.load(file_paths[0], map_location="cpu", weights_only=True)
                
                load_time = time.perf_counter() - start_time
                file_size = os.path.getsize(file_paths[0])
                
                torch_stats.append({
                    'time': load_time,
                    'size': file_size,
                    'throughput_gbps': (file_size / (1024**3)) / load_time
                })
                del data  # Clean up
            except Exception as e:
                logger.error(f"❌ Torch load failed: {e}")
    else:
        logger.warning("⚠️  Torch not available, skipping torch load test")
    
    # Test 4: SSD approach
    logger.info(f"\n💾 SSD I/O APPROACH (3 iterations)")
    logger.info("-" * 40)
    ssd_stats = []
    
    if os.path.exists(ssd_file_path):
        for i in range(iterations):
            logger.info(f"\n--- SSD I/O iteration {i+1}/{iterations} ---")
            start_time = time.perf_counter()
            try:
                with open(ssd_file_path, 'rb') as f:
                    data = f.read()
                    file_size = len(data)
                    del data  # Clean up immediately
                load_time = time.perf_counter() - start_time
                
                ssd_stats.append({
                    'time': load_time,
                    'size': file_size,
                    'throughput_gbps': (file_size / (1024**3)) / load_time
                })
            except Exception as e:
                logger.error(f"❌ SSD I/O load failed: {e}")
    else:
        logger.warning(f"⚠️  SSD file not found: {ssd_file_path}, skipping SSD test")
    
    # Compare results
    logger.info(f"\n📊 PERFORMANCE COMPARISON")
    logger.info("=" * 60)
    
    # Calculate averages for each approach
    results = {}
    
    if usrbio_stats:
        results['usrbio'] = {
            'time': sum(s['time'] for s in usrbio_stats) / len(usrbio_stats),
            'throughput': sum(s['throughput_gbps'] for s in usrbio_stats) / len(usrbio_stats),
            'count': len(usrbio_stats)
        }
    
    if standard_stats:
        results['standard'] = {
            'time': sum(s['time'] for s in standard_stats) / len(standard_stats),
            'throughput': sum(s['throughput_gbps'] for s in standard_stats) / len(standard_stats),
            'count': len(standard_stats)
        }
    
    if torch_stats:
        results['torch'] = {
            'time': sum(s['time'] for s in torch_stats) / len(torch_stats),
            'throughput': sum(s['throughput_gbps'] for s in torch_stats) / len(torch_stats),
            'count': len(torch_stats)
        }
    
    if ssd_stats:
        results['ssd'] = {
            'time': sum(s['time'] for s in ssd_stats) / len(ssd_stats),
            'throughput': sum(s['throughput_gbps'] for s in ssd_stats) / len(ssd_stats),
            'count': len(ssd_stats)
        }
    
    if results:
        logger.success(f"🎯 RESULTS:")
        
        # Display results for each approach
        if 'usrbio' in results:
            logger.info(f"   🚀 USRBIO:")
            logger.info(f"      Average time: {results['usrbio']['time']:.3f}s")
            logger.info(f"      Average throughput: {results['usrbio']['throughput']:.2f} GB/s")
            logger.info(f"      Runs: {results['usrbio']['count']}")
        
        if 'standard' in results:
            logger.info(f"   📁 Standard I/O:")
            logger.info(f"      Average time: {results['standard']['time']:.3f}s")
            logger.info(f"      Average throughput: {results['standard']['throughput']:.2f} GB/s")
            logger.info(f"      Runs: {results['standard']['count']}")
        
        if 'torch' in results:
            logger.info(f"   🔥 Torch Load:")
            logger.info(f"      Average time: {results['torch']['time']:.3f}s")
            logger.info(f"      Average throughput: {results['torch']['throughput']:.2f} GB/s")
            logger.info(f"      Runs: {results['torch']['count']}")
        
        if 'ssd' in results:
            logger.info(f"   💾 SSD I/O:")
            logger.info(f"      Average time: {results['ssd']['time']:.3f}s")
            logger.info(f"      Average throughput: {results['ssd']['throughput']:.2f} GB/s")
            logger.info(f"      Runs: {results['ssd']['count']}")
        
        # Performance comparisons (using USRBIO as baseline if available)
        if 'usrbio' in results:
            logger.success(f"\n⚡ SPEEDUP COMPARISONS (vs USRBIO):")
            baseline_time = results['usrbio']['time']
            
            if 'standard' in results:
                speedup = results['standard']['time'] / baseline_time
                logger.info(f"   📁 Standard I/O: {speedup:.2f}x {'slower' if speedup > 1 else 'faster'}")
            
            if 'torch' in results:
                speedup = results['torch']['time'] / baseline_time
                logger.info(f"   🔥 Torch Load: {speedup:.2f}x {'slower' if speedup > 1 else 'faster'}")
            
            if 'ssd' in results:
                speedup = results['ssd']['time'] / baseline_time
                logger.info(f"   💾 SSD I/O: {speedup:.2f}x {'slower' if speedup > 1 else 'faster'}")
        
        # Find fastest approach
        fastest = min(results.keys(), key=lambda k: results[k]['time'])
        logger.success(f"\n🏆 FASTEST APPROACH: {fastest.upper()}")
        logger.info(f"   Time: {results[fastest]['time']:.3f}s")
        logger.info(f"   Throughput: {results[fastest]['throughput']:.2f} GB/s")
        
        logger.info(f"\n🎯 KEY INSIGHTS:")
        logger.info(f"   🚀 USRBIO provides direct async I/O with shared memory")
        logger.info(f"   📁 Standard I/O uses regular file system calls")
        logger.info(f"   🔥 Torch loading includes deserialization overhead")
        logger.info(f"   💾 SSD performance depends on local storage speed")
        
        logger.info(f"\n💡 RECOMMENDATIONS:")
        logger.info(f"   • Use USRBIO for maximum I/O performance on distributed filesystems")
        logger.info(f"   • Consider SSD caching for frequently accessed files")
        logger.info(f"   • Torch loading is convenient but includes parsing overhead")
        logger.info(f"   • Standard I/O is simple but may be slower on networked storage")
        
    else:
        logger.error("❌ No successful tests to compare")

    # Clean up USRBIO resources using new pattern
    logger.info(f"\n🧹 CLEANING UP USRBIO RESOURCES...")
    for resource in usrbio_results:
        loader_bytes.deallocate(resource)
    gc.collect()
    logger.info(f"✅ Resource cleanup complete")

    # Also run the original comprehensive benchmark for reference
    logger.info(f"\n" + "=" * 60)
    logger.info("🏁 COMPREHENSIVE BENCHMARK (all approaches)")
    benchmark_usrbio_vs_standard(file_paths, include_ssd=True, runs=1)
