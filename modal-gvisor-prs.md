# google/gvisor PRs by Modal employees

Identified via @modal.com commit emails. As of 2026-10-06. Note: gVisor lands many PRs through Copybara, so some PRs marked "closed" did land as commits (e.g. #14449, #13878, #13657, #12945).

## Ayush Ranjan (@ayushr2): 35 PRs (23 merged, 7 open, 5 closed unmerged)

| Date | PR | State | Title |
|---|---|---|---|
| 2026-10-06 | [#15377](https://github.com/google/gvisor/pull/15377) | open | nvproxy: Reject OS descriptors without a handle |
| 2026-10-06 | [#15365](https://github.com/google/gvisor/pull/15365) | open | nvproxy: move HostDriverVersion into nvconf; resolve latest in sentry |
| 2026-10-06 | [#15359](https://github.com/google/gvisor/pull/15359) | open | runsc/sandbox: drop the netstack and plugin-stack imports |
| 2026-10-06 | [#15358](https://github.com/google/gvisor/pull/15358) | merged | xdp: move the bpffs pin-path helpers into pkg/xdp |
| 2026-10-06 | [#15357](https://github.com/google/gvisor/pull/15357) | merged | specutils: stop importing the OCI seccomp compiler |
| 2026-10-06 | [#15356](https://github.com/google/gvisor/pull/15356) | open | hostmm: move IMAWorkAroundForMemFile out of pgalloc |
| 2026-10-06 | [#15355](https://github.com/google/gvisor/pull/15355) | open | seccheck, auth: drop stale deps and the auth -> seccheck edge |
| 2026-10-06 | [#15354](https://github.com/google/gvisor/pull/15354) | open | nvproxy: Support NVOS32_FUNCTION_ALLOC_OS_DESCRIPTOR on fixed drivers |
| 2026-09-25 | [#15004](https://github.com/google/gvisor/pull/15004) | closed | runsc: add build flag to elide embedded sidecar binaries |
| 2026-09-23 | [#14950](https://github.com/google/gvisor/pull/14950) | open | rdmaproxy: support UCX-based data planes (epoll, comp channels, SRQ) |
| 2026-09-23 | [#14939](https://github.com/google/gvisor/pull/14939) | closed | mm: unmap platform AddressSpace before punching partial huge pages |
| 2026-09-23 | [#14911](https://github.com/google/gvisor/pull/14911) | merged | nvproxy: restore version.go changes clobbered by 0662a64ef591 |
| 2026-09-21 | [#14858](https://github.com/google/gvisor/pull/14858) | merged | rdmaproxy: handle legacy write-ABI commands explicitly |
| 2026-09-02 | [#14567](https://github.com/google/gvisor/pull/14567) | merged | Reproduce host errno for unreadable RDMA netdev sysfs attributes. |
| 2026-08-31 | [#14526](https://github.com/google/gvisor/pull/14526) | merged | Cap host CPU deep idle states for GPU sandboxes on impacted CPUs. |
| 2026-08-31 | [#14525](https://github.com/google/gvisor/pull/14525) | merged | Create nvproxy device files on restore regardless of remap metadata. |
| 2026-08-26 | [#14426](https://github.com/google/gvisor/pull/14426) | merged | systrap: preserve latency medians across histogram reset |
| 2026-08-21 | [#14258](https://github.com/google/gvisor/pull/14258) | merged | mm: restore file data after partial huge-page MADV_DONTNEED |
| 2026-08-20 | [#14221](https://github.com/google/gvisor/pull/14221) | merged | Support RENAME_EXCHANGE in tmpfs and overlayfs |
| 2026-08-10 | [#14055](https://github.com/google/gvisor/pull/14055) | merged | nvproxy: add control commands used by Nsight Compute |
| 2026-08-07 | [#14042](https://github.com/google/gvisor/pull/14042) | closed | socket/netlink: implement NETLINK_RDMA to report copy-on-fork |
| 2026-08-07 | [#14035](https://github.com/google/gvisor/pull/14035) | merged | fsimpl/erofs: read regular file data directly from the image FD |
| 2026-08-07 | [#14031](https://github.com/google/gvisor/pull/14031) | merged | mm: implement copy-on-fork for pinned pages |
| 2026-08-05 | [#14000](https://github.com/google/gvisor/pull/14000) | merged | Create /dev/char and /dev/block symlinks in devtmpfs |
| 2026-08-04 | [#13989](https://github.com/google/gvisor/pull/13989) | merged | nvproxy: support NV2080_CTRL_CMD_PERF_GET_GPUMON_PERFMON_UTIL_SAMPLES_V2 |
| 2026-08-03 | [#13955](https://github.com/google/gvisor/pull/13955) | merged | nvproxy: return realistic sets from PopularCapabilitySets() |
| 2026-07-31 | [#13941](https://github.com/google/gvisor/pull/13941) | merged | pgalloc: throttle UpdateUsage() scans in proportion to their cost |
| 2026-07-28 | [#13882](https://github.com/google/gvisor/pull/13882) | merged | Add AWS EFA support to rdmaproxy |
| 2026-07-28 | [#13878](https://github.com/google/gvisor/pull/13878) | closed | runsc: make TPU proxy sysfs bind mounts actually read-only |
| 2026-07-21 | [#13779](https://github.com/google/gvisor/pull/13779) | merged | Add RDMA uverbs device proxy |
| 2026-07-16 | [#13736](https://github.com/google/gvisor/pull/13736) | merged | nvproxy: support exporting GPU memory to a dma-buf fd |
| 2026-07-16 | [#13725](https://github.com/google/gvisor/pull/13725) | merged | nvproxy: add NVIDIA driver 580.95.05 as unsupported |
| 2026-07-15 | [#13714](https://github.com/google/gvisor/pull/13714) | merged | Document why application memory appears as shmem in cgroup stats. |
| 2026-07-15 | [#13712](https://github.com/google/gvisor/pull/13712) | merged | Add RDMA sysfs topology construction for gVisor sandboxes |
| 2026-07-09 | [#13657](https://github.com/google/gvisor/pull/13657) | closed | website: register fuse user guide doc |

## Luis Capelo (@luiscape): 32 PRs (18 merged, 3 open, 11 closed unmerged)

| Date | PR | State | Title |
|---|---|---|---|
| 2026-09-23 | [#14940](https://github.com/google/gvisor/pull/14940) | open | systrap: return bare errno from stub syscalls |
| 2026-09-21 | [#14863](https://github.com/google/gvisor/pull/14863) | closed | nvproxy: track device mappings so `InvalidateUnsavable` drops them before save |
| 2026-09-21 | [#14860](https://github.com/google/gvisor/pull/14860) | closed | nvproxy: find CUDA processes in every task's FD table and order them deterministically |
| 2026-09-19 | [#14850](https://github.com/google/gvisor/pull/14850) | merged | nvproxy: support NV2080_CTRL_CMD_FLA_GET_FABRIC_MEM_STATS |
| 2026-09-17 | [#14817](https://github.com/google/gvisor/pull/14817) | open | Implement --device-map in cuda-checkpoint restore |
| 2026-09-14 | [#14751](https://github.com/google/gvisor/pull/14751) | merged | nvproxy: Add support for NVIDIA driver version 615.71.09 |
| 2026-08-18 | [#14159](https://github.com/google/gvisor/pull/14159) | closed | nvproxy: remove stale device files when restoring onto different GPUs |
| 2026-08-14 | [#14134](https://github.com/google/gvisor/pull/14134) | merged | Add an empty `/proc/modules` to procfs. |
| 2026-08-06 | [#14008](https://github.com/google/gvisor/pull/14008) | merged | mm: implement `MAP_FIXED_NOREPLACE` |
| 2026-08-05 | [#14005](https://github.com/google/gvisor/pull/14005) | merged | nvproxy: support NV_EVENT_BUFFER |
| 2026-08-05 | [#14002](https://github.com/google/gvisor/pull/14002) | merged | nvproxy: expose CLOCK_MONOTONIC_RAW as a distinct clock for capProfiling |
| 2026-08-04 | [#13994](https://github.com/google/gvisor/pull/13994) | closed | nvproxy: support NV01_MEMORY_DEVICELESS and GR SM_ISSUE_RATE_MODIFIER_V2 |
| 2026-08-04 | [#13987](https://github.com/google/gvisor/pull/13987) | open | Support for starting sandboxes with cuda-checkpoint |
| 2026-08-04 | [#13976](https://github.com/google/gvisor/pull/13976) | merged | Adds support for NVIDIA driver 610.57.04 |
| 2026-07-31 | [#13933](https://github.com/google/gvisor/pull/13933) | closed | Fix CUDA process enumeration race in checkpoint |
| 2026-07-16 | [#13734](https://github.com/google/gvisor/pull/13734) | merged | Adds missing NVIDIA video engine classes |
| 2026-07-08 | [#13644](https://github.com/google/gvisor/pull/13644) | merged | Add CUDA GPU coredump support to nvproxy |
| 2026-06-23 | [#13551](https://github.com/google/gvisor/pull/13551) | merged | tmpfs: decouple `regularFile.Translate()` fill range from translation range |
| 2026-06-18 | [#13501](https://github.com/google/gvisor/pull/13501) | merged | Populate CPU statistics in `/proc/stat` |
| 2026-06-17 | [#13484](https://github.com/google/gvisor/pull/13484) | merged | Add NVIDIA MPS support to nvproxy |
| 2026-06-05 | [#13377](https://github.com/google/gvisor/pull/13377) | merged | nvproxy: don't pass privileged driver caps to `nvidia-container-cli` |
| 2026-06-01 | [#13335](https://github.com/google/gvisor/pull/13335) | merged | Adds missing `NV_COUNTER_COLLECTION_UNIT` to CapProfiling |
| 2026-04-14 | [#12945](https://github.com/google/gvisor/pull/12945) | closed | Adds device, ioctls, and new CapProfiling capability |
| 2026-04-14 | [#12940](https://github.com/google/gvisor/pull/12940) | closed | Adds nvproxy ioctls to support nsight |
| 2026-04-03 | [#12867](https://github.com/google/gvisor/pull/12867) | merged | Adds missing video encoding NVIDIA ioctl classes |
| 2026-03-30 | [#12818](https://github.com/google/gvisor/pull/12818) | closed | Adds Vulkan ICD JSON and other utility files automatically, if available |
| 2026-03-29 | [#12817](https://github.com/google/gvisor/pull/12817) | merged | Adds missing Vulkan ioctls for RTX PRO 6000 |
| 2026-03-27 | [#12805](https://github.com/google/gvisor/pull/12805) | closed | nvproxy: Fixes performance degradation for GPU→CPU pageable transfer bandwidth |
| 2026-03-14 | [#12734](https://github.com/google/gvisor/pull/12734) | merged | Adds Blackwell video encoder classes |
| 2025-06-08 | [#11799](https://github.com/google/gvisor/pull/11799) | closed | Add support for 575.57.08 |
| 2024-07-03 | [#10610](https://github.com/google/gvisor/pull/10610) | merged | nvproxy: add missing UVM_UNMAP_EXTERNAL ioctl |
| 2023-11-07 | [#9650](https://github.com/google/gvisor/pull/9650) | closed | Allows `driverABI` to be saveable |

## Botir Khaltaev (@botirkhaltaev): 15 PRs (5 merged, 3 open, 7 closed unmerged)

| Date | PR | State | Title |
|---|---|---|---|
| 2026-10-06 | [#15367](https://github.com/google/gvisor/pull/15367) | open | Log user frame-pointer chains in debug state dumps |
| 2026-10-04 | [#15290](https://github.com/google/gvisor/pull/15290) | open | nvproxy: handle Blackwell profiler control commands used by CUPTI |
| 2026-10-01 | [#15186](https://github.com/google/gvisor/pull/15186) | open | nvproxy: add control commands used by NVIDIA DCGM |
| 2026-09-26 | [#15046](https://github.com/google/gvisor/pull/15046) | closed | nvproxy: support NV00FE_CTRL_CMD_SUBMIT_PAGING_OPERATIONS |
| 2026-09-26 | [#15045](https://github.com/google/gvisor/pull/15045) | merged | nvproxy: support NV00FE memory mapper control commands |
| 2026-09-17 | [#14816](https://github.com/google/gvisor/pull/14816) | merged | Add AT_PLATFORM to the initial auxv |
| 2026-09-15 | [#14776](https://github.com/google/gvisor/pull/14776) | closed | mm: keep ranges unmapped during cuda-checkpoint reserved until restore |
| 2026-08-28 | [#14472](https://github.com/google/gvisor/pull/14472) | closed | mm: reserve contiguous MemoryFile spans for private anonymous mappings |
| 2026-08-27 | [#14454](https://github.com/google/gvisor/pull/14454) | merged | systrap: rate-limit the ptrace-with-patched-syscalls warning |
| 2026-08-27 | [#14450](https://github.com/google/gvisor/pull/14450) | merged | nvproxy: include ngx in "all" container driver capabilities |
| 2026-08-27 | [#14449](https://github.com/google/gvisor/pull/14449) | closed | nvproxy: support AMPERE_B and GET_HS_CREDITS_MAPPING |
| 2026-08-11 | [#14070](https://github.com/google/gvisor/pull/14070) | closed | nvproxy: support PERF_RATED_TDP clock lock controls |
| 2026-08-11 | [#14069](https://github.com/google/gvisor/pull/14069) | merged | nvproxy: support MAXWELL_PROFILER_CONTEXT allocation class |
| 2026-08-10 | [#14058](https://github.com/google/gvisor/pull/14058) | closed | nvproxy: support NVB0CC_CTRL_CMD_GET_CHIPLET_HS_CREDIT_POOL |
| 2026-08-10 | [#14057](https://github.com/google/gvisor/pull/14057) | closed | nvproxy: support NV2080_CTRL_CMD_GR_GET_SM_ISSUE_THROTTLE_CTRL |

## Jonathon Belotti (@thundergolfer): 12 PRs (11 merged, 0 open, 1 closed unmerged)

| Date | PR | State | Title |
|---|---|---|---|
| 2025-05-21 | [#11754](https://github.com/google/gvisor/pull/11754) | merged | Update docker-in-gvisor.md |
| 2024-10-18 | [#11057](https://github.com/google/gvisor/pull/11057) | merged | nvproxy: remove outdated commentary |
| 2024-09-15 | [#10915](https://github.com/google/gvisor/pull/10915) | merged | docs: update out-of-date and mispelled lines in debugging.md |
| 2024-07-11 | [#10649](https://github.com/google/gvisor/pull/10649) | merged | nvproxy: implement missing NV_MEMORY_MULTICAST_FABRIC, NV00FD_* |
| 2024-07-02 | [#10603](https://github.com/google/gvisor/pull/10603) | merged | nvproxy: add missing UVM peer access ioctls |
| 2024-05-26 | [#10484](https://github.com/google/gvisor/pull/10484) | closed | Implement a few sysfs CPU topology files (for hwloc) |
| 2024-05-12 | [#10434](https://github.com/google/gvisor/pull/10434) | merged | Partially address Issue #10413 by adding NV0000_CTRL_CMD_OS_UNIX_GET_EXPORT_OBJECT_INFO, NV0000_CTRL_CMD_OS_UNIX_IMPORT_OBJECT_FROM_FD, NV0041_CTRL_CMD_GET_SURFACE_INFO |
| 2024-05-08 | [#10402](https://github.com/google/gvisor/pull/10402) | merged | add strace dbg processing for 'faccessat2' |
| 2023-11-13 | [#9700](https://github.com/google/gvisor/pull/9700) | merged | Support nvmlDeviceGetComputeRunningProcesses_ in nvproxy to fix PyTorch OOM handling |
| 2023-11-09 | [#9669](https://github.com/google/gvisor/pull/9669) | merged | provide (read only) /proc/sys/kernel/overflowuid and overflowgid |
| 2023-10-04 | [#9450](https://github.com/google/gvisor/pull/9450) | merged | fix: outdated line in debugging.md doc |
| 2023-09-04 | [#9336](https://github.com/google/gvisor/pull/9336) | merged | Fix EOF (^D) handling in devpts (partially addr #9333) |

## Daniel Norberg (@danielnorberg): 3 PRs (2 merged, 1 open, 0 closed unmerged)

| Date | PR | State | Title |
|---|---|---|---|
| 2026-02-22 | [#12635](https://github.com/google/gvisor/pull/12635) | open | Add --path flag to runsc tar rootfs-upper for subtree exports |
| 2026-02-22 | [#12633](https://github.com/google/gvisor/pull/12633) | merged | Fix rootfs-upper tar to preserve opaque xattrs |
| 2026-01-06 | [#12447](https://github.com/google/gvisor/pull/12447) | merged | vfs: validate source/target type match in BindAt |

## Amit Prasad (@AmitPr): 2 PRs (2 merged, 0 open, 0 closed unmerged)

| Date | PR | State | Title |
|---|---|---|---|
| 2026-04-07 | [#12886](https://github.com/google/gvisor/pull/12886) | merged | Add `control-rpc-stop-timeout` flag for control socket |
| 2026-04-07 | [#12884](https://github.com/google/gvisor/pull/12884) | merged | cgroupsv2 supports `linux.resources.unified` from OCI spec |

## Apoorva Bhagwat (@abhagwat): 2 PRs (2 merged, 0 open, 0 closed unmerged)

| Date | PR | State | Title |
|---|---|---|---|
| 2025-08-22 | [#12079](https://github.com/google/gvisor/pull/12079) | merged | Implement the `beforeSave` hook for `processorManager` |
| 2025-08-20 | [#12064](https://github.com/google/gvisor/pull/12064) | merged | Fix stringification code for `headerType` (under `pkg/tcpip/stack`). |

## Colin (@cweld510): 2 PRs (2 merged, 0 open, 0 closed unmerged)

| Date | PR | State | Title |
|---|---|---|---|
| 2024-12-27 | [#11323](https://github.com/google/gvisor/pull/11323) | merged | Add flag to disable container spec validation when restoring checkpoints |
| 2024-10-04 | [#10996](https://github.com/google/gvisor/pull/10996) | merged | Extend -net-disconnect-ok to close unsaveable unix sockets on save |

## Nicolas Lara (@nicolaslara): 1 PRs (1 merged, 0 open, 0 closed unmerged)

| Date | PR | State | Title |
|---|---|---|---|
| 2026-08-27 | [#14447](https://github.com/google/gvisor/pull/14447) | merged | fuse: add no_create fallback and offer ATOMIC_O_TRUNC/BIG_WRITES in INIT |

## Peyton Walters (@pawalt): 1 PRs (1 merged, 0 open, 0 closed unmerged)

| Date | PR | State | Title |
|---|---|---|---|
| 2024-11-05 | [#11124](https://github.com/google/gvisor/pull/11124) | merged | Implement /proc/sys/kernel/pid_max with TasksLimit |

