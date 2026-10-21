# 3FS Deep Dive: Architecture, Read/Write Paths, and Performance Bottlenecks

This document provides a comprehensive technical analysis of the Fire-Flyer File System (3FS), focusing on how reads and writes work through the system, the overall architecture, and identified performance bottlenecks.

## Table of Contents
1. [Architecture Overview](#architecture-overview)
2. [Read Path](#read-path)
3. [Write Path](#write-path)
4. [Key Components Deep Dive](#key-components-deep-dive)
5. [Performance Bottlenecks](#performance-bottlenecks)
6. [Optimization Opportunities](#optimization-opportunities)

---

## Architecture Overview

3FS is a high-performance distributed file system designed for AI training and inference workloads. It consists of four main components connected via RDMA network (InfiniBand or RoCE):

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        RDMA Network (InfiniBand/RoCE)                        │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                               │
│  ┌────────────────┐    ┌────────────────┐    ┌─────────────────────────┐    │
│  │    Clients     │    │    Metadata    │    │    Storage Service      │    │
│  │ (FUSE/Native)  │───▶│    Service     │───▶│    (CRAQ Chains)        │    │
│  │                │    │  (Stateless)   │    │    (NVMe SSDs)          │    │
│  └────────────────┘    └────────────────┘    └─────────────────────────┘    │
│         ↑                      ↑                         ↑                   │
│         └──────────────────────┴─────────────────────────┘                   │
│                                                                               │
│                   ┌────────────────────────────┐                             │
│                   │     Cluster Manager        │                             │
│                   │ (Membership, Chain Tables) │                             │
│                   └────────────────────────────┘                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Component Responsibilities

| Component | Role | Implementation |
|-----------|------|----------------|
| **Cluster Manager** | Membership management, chain table distribution | Primary election via ZooKeeper/etcd |
| **Metadata Service** | File operations, layout info, permissions | Stateless, backed by FoundationDB |
| **Storage Service** | Data storage, CRAQ replication | Multiple SSDs per node, chunk engine |
| **Clients** | Application interface | FUSE daemon or native io_uring API |

### Data Organization

Files are divided into equally-sized chunks and striped across multiple replication chains:

- **Chunk sizes**: 64KB, 512KB, or 4MB (configurable per directory)
- **Chunk ID**: Concatenation of file's inode ID + chunk index
- **Replication**: Chain Replication with Apportioned Queries (CRAQ)

---

## Read Path

### High-Level Flow

```
Application → FUSE/Native API → Chunk ID Calculation → Storage Service → SSD → Response
```

### Detailed Read Steps

#### 1. Application Layer (`src/fuse/FuseOps.cc`)
```cpp
// FUSE read entry point intercepts read syscalls
hf3fs_read(fuse_req_t req, fuse_ino_t fino, size_t size, off_t off, struct fuse_file_info *fi)
```

#### 2. Chunk ID Calculation (Client-side)
The client independently computes which chunks to read:
```
ChunkId = (InodeId, ChunkIndex)
ChunkIndex = offset / chunk_size
ChainId = lookup(inode.chain_table, shuffled_index)
```

**Key insight**: Clients can compute chunk IDs without contacting metadata service after `open()`.

#### 3. Target Selection (`src/client/storage/TargetSelection.cc`)
- Read requests can go to **any replica** in the chain (unlike writes)
- Load balancing distributes reads across all targets
- This is CRAQ's "read-any" optimization

#### 4. Storage Service Processing (`src/storage/service/StorageOperator.cc`)
```cpp
CoTryTask<BatchReadRsp> batchRead(ServiceRequestContext &requestCtx,
                                   const BatchReadReq &req,
                                   serde::CallContext &ctx)
```

The read path at storage service:
1. **Version Check**: If only committed version exists → return data
2. **Pending Version**: If both committed + pending versions exist:
   - Return special status code (not the data)
   - Client retries after short interval, OR
   - Client requests "relaxed read" to get pending version

#### 5. Chunk Engine Read (`src/storage/chunk_engine/`)
```
// Read returns Arc<ChunkPos> ensuring safe data access (Rust pseudocode)
fn read(chunk_id: ChunkId) -> Result<(ChunkMeta, Arc<ChunkPos>)>
```

The `Arc<ChunkPos>` reference ensures the chunk's physical location remains valid until read completes, even during concurrent writes/deletes.

### Read Performance Characteristics

- **RDMA zero-copy**: Data transferred directly from SSD buffer to client memory
- **No metadata involvement**: After `open()`, reads bypass metadata service entirely
- **Parallel reads**: Multiple chunks can be read concurrently from different chains
- **Load balanced**: Traffic distributed across all replicas in chain

---

## Write Path

### High-Level Flow

```
Application → FUSE/Native API → Metadata Sync → Head Target → Chain Propagation → ACK (Acknowledgment)
```

### Detailed Write Steps

#### 1. Application Layer (`src/fuse/FuseOps.cc`)
```cpp
// Write buffer flush implementation
CoTryTask<ssize_t> flushBuf(const flat::UserInfo &user,
                             const std::shared_ptr<RcInode> &pi,
                             const off_t off,
                             storage::client::IOBuffer &memh,
                             const size_t len,
                             bool flushAll)
```

#### 2. PioV Write Preparation (`src/fuse/PioV.h`)
```cpp
// Add write to batch
Result<Void> addWrite(size_t idx, const meta::Inode &inode, uint16_t track,
                      off_t off, size_t len, const void *buf, IOBuffer &memh);

// Execute batched writes
CoTryTask<void> executeWrite(const UserInfo &userInfo, const WriteOptions &options);
```

#### 3. Metadata Coordination
Before writing, client may need to:
- Verify file is open for write
- Update file session with metadata service
- Get latest file layout information

#### 4. CRAQ Chain Replication (`src/storage/service/StorageOperator.cc`)

The write flow through CRAQ:

```
┌─────────┐    ┌─────────┐    ┌─────────┐    ┌─────────┐
│ Client  │───▶│  Head   │───▶│ Middle  │───▶│  Tail   │
│         │    │ Target  │    │ Target  │    │ Target  │
└─────────┘    └────┬────┘    └────┬────┘    └────┬────┘
                    │              │              │
                    │   Forward    │   Forward    │
                    │─────────────▶│─────────────▶│
                    │              │              │
                    │              │     ACK      │
                    │◀─────────────│◀─────────────│
                    │     ACK      │              │
                    ▼              ▼              ▼
              [Committed]    [Committed]    [Committed]
```

**Step-by-step at each storage target:**

1. **Chain Version Check** ([design_notes.md](design_notes.md), line 155)
   ```cpp
   if (req.chainVersion != latestKnownVersion) {
     reject(request);
   }
   ```

2. **RDMA Data Pull**
   ```cpp
   // Storage service issues RDMA Read to pull write data
   // This is zero-copy from client's registered memory
   ```

3. **Chunk Lock Acquisition** ([design_notes.md](design_notes.md), line 159)
   ```cpp
   // Lock manager serializes concurrent writes to same chunk
   auto lock = lockManager.acquire(chunkId);
   ```

4. **Update Processing** ([design_notes.md](design_notes.md), line 161)
   ```cpp
   // Read committed version, apply update, store as pending
   committed_version = readChunk(chunkId);
   pending_version = applyUpdate(committed_version, writeData);
   // pending.version = committed.version + 1
   ```

5. **Forward or Commit**
   - If **not tail**: Forward to successor
   - If **tail**: Replace committed with pending, send ACK backward

6. **ACK Propagation**
   - Each target replaces committed with pending upon receiving ACK
   - Releases chunk lock
   - Propagates ACK to predecessor

### Write Concurrency Control

From `StorageOperator.h`:
```cpp
CONFIG_HOT_UPDATED_ITEM(max_concurrent_rdma_writes, 256U);
CONFIG_HOT_UPDATED_ITEM(max_concurrent_rdma_reads, 256U);
```

Semaphores limit concurrent RDMA operations per device to prevent congestion.

---

## Key Components Deep Dive

### Chunk Engine (`src/storage/chunk_engine/`)

The chunk engine manages physical storage with copy-on-write semantics:

#### Storage Hierarchy
```
Node (10-20 disks)
  └── Disk (30TB, 256 files per chunk size)
       └── File (~120GB for 512KB chunks, ~960 groups)
            └── Group (256 chunks = 16MB-1GB)
                 └── Chunk (64KB, 512KB, or 4MB)
```

#### Allocator Design
```
// In-memory structures for fast allocation (Rust pseudocode)
struct Allocator {
    active_groups: HashMap<GroupId, GroupState>,   // Currently allocating
    allocated_groups: Vec<GroupId>,                // Space allocated, no chunks
    unallocated_groups: Vec<GroupId>,              // No space allocated
}
```

- **Allocation**: Uses `__builtin_ctz` for O(1) bit scanning
- **Background threads**:
  - `allocate_thread`: Keeps `active_groups` within target range
  - `compact_thread`: Migrates chunks, reclaims fragmented groups

#### Write Workflow
1. Allocator assigns new chunk position (in-memory)
2. Write data to new position (safe if power failure)
3. Atomic persist via RocksDB WriteBatch

### Lock Manager (`src/common/utils/LockManager.h`)

Provides chunk-level locking for write serialization:
- All writes to same chunk serialize at head target
- Fine-grained locks prevent contention across different chunks
- Critical for maintaining CRAQ consistency

### FUSE Integration (`src/fuse/`)

#### Standard FUSE Path
```
Application syscall → Kernel FUSE → User-space daemon → 3FS client
```

#### Native Zero-Copy API (bypasses FUSE limitations)
```cpp
// Iov: Large memory region for zero-copy I/O
// Ior: Ring buffer for request/completion (like io_uring)
```

Key structures from `IoRing.h` and `IovTable.h` enable:
- RDMA-registered memory regions
- Batched I/O submission
- Asynchronous completion

---

## Performance Bottlenecks

### 1. FUSE Kernel Limitations

**Location**: Kernel FUSE module

**Problem**: 
- Spin lock on FUSE queue limits throughput to ~400K 4KB reads/sec
- Memory copy overhead between kernel and userspace
- No concurrent writes to same file on certain Linux kernel versions (see [design_notes.md](design_notes.md), line 33)

**Evidence** ([design_notes.md](design_notes.md), line 31):
> "perf profiling reveals that the kernel-space spin lock consumes a significant amount of CPU time"

**Impact**: High for small random reads; workaround is native API.

### 2. Write Serialization at Head Target

**Location**: `src/storage/service/StorageOperator.cc`

**Problem**: 
- All writes to the **same chunk** are blocked at head target
- Lock manager serializes concurrent writes to the same chunk
- Chain propagation adds latency

**Evidence** ([design_notes.md](design_notes.md), line 159):
> "Concurrent writes to the same chunk are blocked. All writes are serialized at the head target."

**Impact**: High for write-heavy workloads with hot chunks.

### 3. RDMA Concurrency Limits

**Location**: `src/storage/service/StorageOperator.h:39-40`

```cpp
CONFIG_HOT_UPDATED_ITEM(max_concurrent_rdma_writes, 256U);
CONFIG_HOT_UPDATED_ITEM(max_concurrent_rdma_reads, 256U);
```

**Problem**: 
- Per-device semaphore limits may throttle under heavy load
- May not fully utilize network bandwidth

**Impact**: Medium; tunable but requires careful balancing.

### 4. File Length Update Overhead

**Location**: Metadata service

**Problem**:
- Requires querying last chunk from storage (non-trivial)
- Concurrent updates cause FoundationDB transaction conflicts
- Auto-retries add latency variance

**Evidence** ([design_notes.md](design_notes.md), line 93):
> "the meta service obtains the precise file length by querying the ID and length of the last chunk from the storage service"

**Mitigation**: Stripe hints (start at 16, double on extension).

### 5. Pending Version Reads

**Location**: `src/storage/service/StorageOperator.cc`

**Problem**:
- When committed + pending versions both exist, read returns special status
- Client must retry or request relaxed read
- Adds latency variance for reads during writes

**Evidence** ([design_notes.md](design_notes.md), line 172):
> "the service replies a special status code to notify the client"

**Impact**: Low for read-heavy workloads; noticeable during concurrent read/write.

### 6. Chain Replication Latency

**Location**: Storage service chain propagation

**Problem**:
- Write must traverse entire chain (N hops for N replicas)
- ACK must propagate backward (another N hops)
- Total: 2N network round trips for write completion

**Impact**: Medium; trades latency for strong consistency.

### 7. Chunk Engine Background Operations

**Location**: `src/storage/chunk_engine/`

**Problem**:
- `allocate_thread` may lag under burst allocation
- `compact_thread` migration can compete with foreground I/O
- `fallocate()` calls during group allocation

**Impact**: Low; mostly affects tail latencies.

---

## Optimization Opportunities

### Priority 1: Reduce Write Serialization Impact
- **Idea**: Optimistic locking for non-overlapping writes to same chunk
- **Trade-off**: Complexity vs. throughput for write-heavy workloads

### Priority 2: RDMA Semaphore Tuning
- **Idea**: Dynamic adjustment based on network saturation metrics
- **Implementation**: Already hot-configurable via `CONFIG_HOT_UPDATED_ITEM`

### Priority 3: Native API Adoption
- **Idea**: Push applications to use native `io_uring`-style API
- **Benefit**: Bypasses all FUSE bottlenecks

### Priority 4: Metadata Stripe Hints
- **Idea**: Profile and tune hint doubling strategy for workload-specific file sizes
- **Benefit**: Reduce metadata queries for small file length updates

### Priority 5: Read-During-Write Handling
- **Idea**: Implement speculative reads that can use pending version
- **Trade-off**: Consistency relaxation must be explicit

### Priority 6: Chain Version Caching
- **Idea**: Client-side caching of chain versions with TTL
- **Benefit**: Reduce version mismatch retries

---

## Summary

3FS achieves high performance through:
1. **CRAQ replication**: Read-any for load balancing, strong consistency
2. **RDMA zero-copy**: Direct memory transfers between nodes
3. **Stateless metadata**: Scalable, easy upgrades
4. **Client-side routing**: Minimal metadata involvement in data path

Key bottlenecks are:
1. **FUSE kernel limitations** (workaround: native API)
2. **Write serialization** (by design for consistency)
3. **Metadata transaction conflicts** (mitigated by distribution)

The system is well-optimized for **read-heavy workloads** typical in AI training (data loading, checkpointing reads). Write bottlenecks are acceptable trade-offs for strong consistency guarantees.
