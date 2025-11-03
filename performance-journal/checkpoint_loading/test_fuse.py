#!/usr/bin/env python3

import os
import time
import multiprocessing.shared_memory
import hf3fs_fuse.io as h3io
import hf3fs_py_usrbio as h3fio

BLOCK_SIZE = 0
CHUNK_SIZE = 1 << 29
MOUNT_POINT = "/3fs/stage"
NUM_FILES = 1
FILE_SIZE = 1 << 31

file_paths = [f"/3fs/stage/fuse/a/test_file_{i}.bin" for i in range(NUM_FILES)]
data_pattern = b"A" * FILE_SIZE

print(f"Writing {NUM_FILES} files of {FILE_SIZE // (1024**3)}GB each using standard I/O")

write_start = time.perf_counter()

for i, file_path in enumerate(file_paths):
    print(f"Writing file {i+1}/{NUM_FILES}: {os.path.basename(file_path)}")
    
    if not os.path.exists(file_path):
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
    
    if os.path.exists(file_path):
        continue

    with open(file_path, 'wb') as f:
        f.write(data_pattern)

write_time = time.perf_counter() - write_start
write_throughput = (NUM_FILES * FILE_SIZE / (1024**3)) / write_time

print(f"Standard write completed in {write_time:.3f}s ({write_throughput:.2f} GB/s)")

print(f"\nReading back files using USRBIO...")

resources = []
read_start = time.perf_counter()

for i, file_path in enumerate(file_paths):
    print(f"Preparing read for file {i+1}/{NUM_FILES}: {os.path.basename(file_path)}")
    
    file_size = os.path.getsize(file_path)
    
    iov = h3fio.iovec(MOUNT_POINT, file_size, BLOCK_SIZE, numa=-1)
    if iov.result != 0:
        print(f"ERROR: Failed to allocate iovec for {file_path}: {iov.result}")
        continue
    
    fd = os.open(file_path, os.O_RDONLY)
    h3fio.register_fd(fd)
    
    ior = h3fio.ioring(
        MOUNT_POINT,
        entries=128,
        for_read=True,
        io_depth=-128,
        priority=0,
        numa=-1,
        flags=0
    )
    
    resources.append({
        'file_path': file_path,
        'file_size': file_size,
        'iov': iov,
        'fd': fd,
        'ior': ior
    })

print("Submitting all read operations...")

for resource in resources:
    resource['ior'].prepare2(
        resource['iov'],
        read=True,
        fd=resource['fd'],
        off=0,
        ptr_offset=0,
        length=resource['file_size'],
        userdata=0
    )
    resource['submitted'] = resource['ior'].submit()

print("Waiting for all read operations to complete...")

all_success = True
for i, resource in enumerate(resources):
    result = resource['submitted'].wait(min_results=1)[0]
    
    if result.result < 0:
        print(f"ERROR: File {i+1} read failed with error {-result.result}")
        all_success = False
    elif result.result != resource['file_size']:
        print(f"ERROR: File {i+1} partial read: {result.result}/{resource['file_size']}")
        all_success = False
    else:
        print(f"SUCCESS: File {i+1} read completely ({result.result} bytes)")
        
        read_data = bytes(resource['iov'].buffer[:resource['file_size']])
        if read_data == data_pattern:
            print(f"VERIFIED: File {i+1} content matches expected pattern")
        else:
            print(f"ERROR: File {i+1} content does not match expected pattern")
            all_success = False

read_completion_time = time.perf_counter()

print("Cleaning up resources...")
for resource in resources:
    h3fio.deregister_fd(resource['fd'])
    os.close(resource['fd'])
    del resource['ior']
    del resource['iov']

read_time = read_completion_time - read_start
read_throughput = (NUM_FILES * FILE_SIZE / (1024**3)) / read_time
total_time = read_completion_time - write_start

print(f"\nRESULTS:")
print(f"Files: {NUM_FILES}")
print(f"File size each: {FILE_SIZE // (1024**3)} GB")
print(f"Total size: {NUM_FILES * FILE_SIZE / (1024**3):.2f} GB")
print(f"Write time: {write_time:.3f}s ({write_throughput:.2f} GB/s)")
print(f"Read time: {read_time:.3f}s ({read_throughput:.2f} GB/s)")
print(f"Total time: {total_time:.3f}s")
print(f"All operations successful: {all_success}")

for file_path in file_paths:
    if os.path.exists(file_path):
        actual_size = os.path.getsize(file_path)
        print(f"File exists: {os.path.basename(file_path)} ({actual_size} bytes)")
    else:
        print(f"ERROR: {os.path.basename(file_path)} not found")
        all_success = False

print(f"\nOVERALL SUCCESS: {all_success}")
