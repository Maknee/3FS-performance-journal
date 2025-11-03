base) makneee@node1:/proj/sdcs-PG0/3fs/3FS-performance-journal/performance-journal/checkpoint_loading$ python benchmark.py --cache_dir /ssd/hf \
    --models \
    deepseek-ai/DeepSeek-R1-Distill-Qwen-32B \
    --runs 1
15:30:38 | INFO     | usrbio_utils:<module> | 🚀 USRBIO core available for direct I/O operations
15:30:38 | INFO     | usrbio_utils:<module> | 🚀 Torch and safetensors available
15:30:38 | INFO     | __main__:benchmark_multiple_models | Starting benchmark with 1 models, 1 runs each
15:30:38 | INFO     | __main__:benchmark_multiple_models | Cache directory: /ssd/hf
15:30:38 | INFO     | __main__:benchmark_multiple_models | Device: CPU
15:30:38 | INFO     | __main__:benchmark_multiple_models | 
--- Model 1/1 ---
15:30:38 | INFO     | __main__:benchmark_model_loading | 
Benchmarking deepseek-ai/DeepSeek-R1-Distill-Qwen-32B loading...
Loading checkpoint shards: 100%|███████████████████████████████████████████████████| 8/8 [00:06<00:00,  1.28it/s]
15:30:46 | INFO     | __main__:benchmark_model_loading | ✅ Used standard loading
15:30:46 | INFO     | __main__:benchmark_model_loading |   Run 1: 8.130s, Memory: +121927.9MB
15:30:50 | INFO     | __main__:benchmark_multiple_models | Average loading time: 8.130s
15:30:50 | INFO     | __main__:benchmark_multiple_models | Average memory usage: +121927.9MB
15:30:50 | INFO     | __main__:print_summary | 
================================================================================
15:30:50 | INFO     | __main__:print_summary | BENCHMARK SUMMARY
15:30:50 | INFO     | __main__:print_summary | ================================================================================
15:30:50 | INFO     | __main__:print_summary | deepseek-ai/DeepSeek-R1-Distill-Qwen-32B |    8.130s | 121927.9MB | 
15:30:50 | INFO     | __main__:save_results | 
Results saved to benchmark_results.json


(base) makneee@node1:/proj/sdcs-PG0/3fs/3FS-performance-journal/performance-journal/checkpoint_loading$ python benchmark.py \
    --cache_dir /3fs/stage/fuse/hf \
    --use-usrbio \
    --direct-sharded-loading \
    --models deepseek-ai/DeepSeek-R1-Distill-Qwen-32B \
    --runs 1
15:31:50 | INFO     | usrbio_utils:<module> | 🚀 USRBIO core available for direct I/O operations
15:31:50 | INFO     | usrbio_utils:<module> | 🚀 Torch and safetensors available
15:31:50 | DEBUG    | usrbio_utils:install_usrbio_hooks | 🔗 HOOK INSTALLED: safetensors.torch.load_file
15:31:50 | DEBUG    | usrbio_utils:install_usrbio_hooks | 🔗 HOOK INSTALLED: safetensors.safe_open
15:31:50 | DEBUG    | usrbio_utils:install_usrbio_hooks | 🔗 HOOK INSTALLED: torch.load
15:31:50 | INFO     | usrbio_utils:install_usrbio_hooks | 🚀 USRBIO hooks installed successfully!
15:31:50 | DEBUG    | usrbio_utils:install_usrbio_hooks |    Mount point: None
15:31:50 | DEBUG    | usrbio_utils:install_usrbio_hooks |    Block size: 1073741824
15:31:50 | DEBUG    | usrbio_utils:install_usrbio_hooks |    Priority: 0
15:31:50 | INFO     | __main__:__init__ | 🚀 USRBIO enabled: mount=None, block_size=1073741824
15:31:50 | INFO     | __main__:__init__ | ⚡ Direct sharded loading enabled with 8 concurrent ops
15:31:50 | INFO     | __main__:benchmark_multiple_models | Starting benchmark with 1 models, 1 runs each
15:31:50 | INFO     | __main__:benchmark_multiple_models | Cache directory: /3fs/stage/fuse/hf
15:31:50 | INFO     | __main__:benchmark_multiple_models | Device: CPU
15:31:50 | INFO     | __main__:benchmark_multiple_models | 🚀 USRBIO ACCELERATION: Enabled
15:31:50 | DEBUG    | __main__:benchmark_multiple_models |    Mount point: None
15:31:50 | DEBUG    | __main__:benchmark_multiple_models |    Block size: 1073741824
15:31:50 | DEBUG    | __main__:benchmark_multiple_models |    Priority: 0
15:31:50 | DEBUG    | __main__:benchmark_multiple_models |    Direct sharded loading: True
15:31:50 | INFO     | __main__:benchmark_multiple_models | 
--- Model 1/1 ---
15:31:50 | INFO     | __main__:benchmark_model_loading | 
Benchmarking deepseek-ai/DeepSeek-R1-Distill-Qwen-32B loading...
15:31:50 | INFO     | __main__:_load_model_with_direct_sharded | 🚀 Attempting direct usrbio sharded loading for deepseek-ai/DeepSeek-R1-Distill-Qwen-32B
15:31:50 | INFO     | usrbio_utils:usrbio_from_pretrained | 🚀 USRBIO from_pretrained: deepseek-ai/DeepSeek-R1-Distill-Qwen-32B
15:31:50 | INFO     | usrbio_utils:usrbio_load_state_dict | 🚀 USRBIO loading state_dict for deepseek-ai/DeepSeek-R1-Distill-Qwen-32B
15:31:50 | DEBUG    | usrbio_utils:usrbio_load_state_dict | 📁 Loading from: /3fs/stage/fuse/hf/models--deepseek-ai--DeepSeek-R1-Distill-Qwen-32B/snapshots/711ad2ea6aa40cfca18895e8aca02ab92df1a746
15:31:50 | DEBUG    | usrbio_utils:usrbio_load_state_dict | 📋 Detected sharded model
15:31:50 | DEBUG    | usrbio_utils:usrbio_load_state_dict | 📋 Found 8 shard files to load
15:31:50 | DEBUG    | usrbio_utils:usrbio_load_state_dict | 🔧 Using batch approach for 8 shards...
15:31:50 | DEBUG    | usrbio_utils:read_files | 🚀 Starting batch read of 8 files
15:31:50 | DEBUG    | usrbio_utils:read_files |   📦 Phase 1: Allocating buffers...
15:31:50 | DEBUG    | usrbio_utils:read_files |   ⏱️  Buffer allocation took: 0.029s
15:31:50 | DEBUG    | usrbio_utils:read_files |   🔧 Phase 2: Submitting reads...
15:31:52 | DEBUG    | usrbio_utils:read_files |   ⏱️  Read submission took: 1.766s
15:31:52 | DEBUG    | usrbio_utils:read_files |   📤 Phase 3: Submitting IO operations...
15:31:52 | DEBUG    | usrbio_utils:read_files |   ⏱️  IO submission took: 0.000s
15:31:52 | DEBUG    | usrbio_utils:read_files |   ⏳ Phase 4: Waiting for completions...
15:31:52 | DEBUG    | usrbio_utils:read_files |     📥 Waiting for file 1/8: model-00007-of-000008.safetensors
15:32:03 | DEBUG    | usrbio_utils:read_files |     ⏱️  File 1 completion took: 11.458s
15:32:03 | DEBUG    | usrbio_utils:read_files |     📥 Waiting for file 2/8: model-00001-of-000008.safetensors
15:32:05 | DEBUG    | usrbio_utils:read_files |     ⏱️  File 2 completion took: 2.130s
15:32:05 | DEBUG    | usrbio_utils:read_files |     📥 Waiting for file 3/8: model-00005-of-000008.safetensors
15:32:06 | DEBUG    | usrbio_utils:read_files |     ⏱️  File 3 completion took: 1.151s
15:32:06 | DEBUG    | usrbio_utils:read_files |     📥 Waiting for file 4/8: model-00002-of-000008.safetensors
15:32:08 | DEBUG    | usrbio_utils:read_files |     ⏱️  File 4 completion took: 1.236s
15:32:08 | DEBUG    | usrbio_utils:read_files |     📥 Waiting for file 5/8: model-00003-of-000008.safetensors
15:32:09 | DEBUG    | usrbio_utils:read_files |     ⏱️  File 5 completion took: 1.138s
15:32:09 | DEBUG    | usrbio_utils:read_files |     📥 Waiting for file 6/8: model-00004-of-000008.safetensors
15:32:10 | DEBUG    | usrbio_utils:read_files |     ⏱️  File 6 completion took: 1.281s
15:32:10 | DEBUG    | usrbio_utils:read_files |     📥 Waiting for file 7/8: model-00008-of-000008.safetensors
15:32:11 | DEBUG    | usrbio_utils:read_files |     ⏱️  File 7 completion took: 0.572s
15:32:11 | DEBUG    | usrbio_utils:read_files |     📥 Waiting for file 8/8: model-00006-of-000008.safetensors
15:32:11 | DEBUG    | usrbio_utils:read_files |     ⏱️  File 8 completion took: 0.776s
15:32:11 | DEBUG    | usrbio_utils:read_files |   ⏱️  Phase 4 (waiting) took: 19.748s
15:32:11 | DEBUG    | usrbio_utils:read_files | 🎯 Batch read completed in 21.543s
15:32:11 | DEBUG    | usrbio_utils:read_files |    Phase breakdown: alloc=0.0s, submit=1.8s, io_submit=0.0s, wait=19.7s
15:32:11 | DEBUG    | usrbio_utils:usrbio_load_state_dict | ⏱️  Batch file loading took: 21.552s
15:32:11 | DEBUG    | usrbio_utils:usrbio_load_state_dict | 🔧 Combining 8 shards into unified state dict...
15:32:11 | DEBUG    | usrbio_utils:usrbio_load_state_dict | ⏱️  Batch combining took: 0.000s
15:32:11 | SUCCESS  | usrbio_utils:usrbio_load_state_dict | ✅ Combined state dict with 0 parameters
15:32:11 | DEBUG    | usrbio_utils:usrbio_from_pretrained | ⏱️  State dict loading took: 21.568s
15:32:11 | SUCCESS  | usrbio_utils:usrbio_from_pretrained | ✅ Using usrbio-loaded state_dict with config-based model creation
15:32:11 | DEBUG    | usrbio_utils:usrbio_from_pretrained | 🔧 Loading model config...
15:32:12 | DEBUG    | usrbio_utils:usrbio_from_pretrained | ⏱️  Config loading took: 0.540s
15:32:12 | DEBUG    | usrbio_utils:usrbio_from_pretrained | 🏗️  Creating model from config (no weights)...
15:32:12 | DEBUG    | usrbio_utils:usrbio_from_pretrained | ⏱️  Model creation took: 0.008s
15:32:12 | SUCCESS  | usrbio_utils:usrbio_from_pretrained | ✅ USRBIO from_pretrained completed in 22.117s
15:32:12 | DEBUG    | usrbio_utils:usrbio_from_pretrained |    Breakdown: state_dict=21.6s, config=0.5s, model_creation=0.0s
15:32:12 | SUCCESS  | __main__:benchmark_model_loading | ✅ Used direct usrbio sharded loading
15:32:12 | INFO     | __main__:benchmark_model_loading |   Run 1: 22.118s, Memory: +1.1MB
15:32:12 | INFO     | __main__:benchmark_multiple_models | Average loading time: 22.118s
15:32:12 | INFO     | __main__:benchmark_multiple_models | Average memory usage: +1.1MB
15:32:12 | SUCCESS  | __main__:benchmark_multiple_models | 🚀 USRBIO acceleration was ACTIVE
15:32:12 | INFO     | __main__:print_summary | 
================================================================================
15:32:12 | INFO     | __main__:print_summary | BENCHMARK SUMMARY
15:32:12 | INFO     | __main__:print_summary | ================================================================================
15:32:12 | INFO     | __main__:print_summary | deepseek-ai/DeepSeek-R1-Distill-Qwen-32B |   22.118s |      1.1MB |  (🚀 USRBIO DIRECT)
15:32:12 | INFO     | __main__:save_results | 
Results saved to benchmark_results.json
15:32:12 | DEBUG    | usrbio_utils:remove_usrbio_hooks | 🔓 HOOK REMOVED: safetensors.torch.load_file
15:32:12 | DEBUG    | usrbio_utils:remove_usrbio_hooks | 🔓 HOOK REMOVED: torch.load
15:32:12 | INFO     | usrbio_utils:remove_usrbio_hooks | 🔓 USRBIO hooks removed
15:32:12 | INFO     | __main__:cleanup | 🔓 USRBIO hooks removed
/users/makneee/mambaforge/lib/python3.12/multiprocessing/resource_tracker.py:254: UserWarning: resource_tracker: There appear to be 8 leaked shared_memory objects to clean up at shutdown
  warnings.warn('resource_tracker: There appear to be %d '
