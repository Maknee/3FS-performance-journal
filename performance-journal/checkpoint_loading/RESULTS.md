USRBIO
================================
18:21:20 | INFO     | __main__:print_summary | BENCHMARK SUMMARY
18:21:20 | INFO     | __main__:print_summary | ================================================================================
18:21:20 | INFO     | __main__:print_summary | deepseek-ai/DeepSeek-R1-Distill-Qwen-32B |   95.589s | 121986.3MB | 
18:21:20 | INFO     | __main__:save_results | 


se python benchmark.py --cache_dir /ssd/hf \
    --drop-caches \
    --models \
    deepseek-ai/DeepSeek-R1-Distill-Qwen-32B \
    --runs 1

LOCAL
=====================================
18:16:51 | INFO     | __main__:print_summary | BENCHMARK SUMMARY
18:16:51 | INFO     | __main__:print_summary | ================================================================================
18:16:51 | INFO     | __main__:print_summary | deepseek-ai/DeepSeek-R1-Distill-Qwen-32B |   14.123s | 121996.7MB | 
18:16:51 | INFO     | __main__:save_results | 

se python benchmark.py \
    --drop-caches \
    --hf3fs-mount-point /3fs/stage \
    --cache_dir /3fs/stage/fuse/hf \
    --use-usrbio \
    --direct-sharded-loading \
    --models deepseek-ai/DeepSeek-R1-Distill-Qwen-32B \
    --usrbio-block-size 0 \
    --usrbio-chunk-size 0 \
    --runs 1

03:34:37 | DEBUG    | usrbio_utils:usrbio_load_state_dict | 🔧 Combining 8 shards into unified state dict...
03:34:37 | DEBUG    | usrbio_utils:usrbio_load_state_dict | ⏱️  Batch combining took: 0.000s
03:34:37 | SUCCESS  | usrbio_utils:usrbio_load_state_dict | ✅ Combined state dict with 0 parameters
03:34:38 | DEBUG    | usrbio_utils:usrbio_from_pretrained | ⏱️  State dict loading took: 17.229s
03:34:38 | SUCCESS  | usrbio_utils:usrbio_from_pretrained | ✅ Using usrbio-loaded state_dict with config-based model creation
03:34:38 | DEBUG    | usrbio_utils:usrbio_from_pretrained | 🔧 Loading model config...
03:34:38 | DEBUG    | usrbio_utils:usrbio_from_pretrained | ⏱️  Config loading took: 0.249s
03:34:38 | DEBUG    | usrbio_utils:usrbio_from_pretrained | 🏗️  Creating model from config (no weights)...
03:34:38 | DEBUG    | usrbio_utils:usrbio_from_pretrained | ⏱️  Model creation took: 0.001s
03:34:38 | SUCCESS  | usrbio_utils:usrbio_from_pretrained | ✅ USRBIO from_pretrained completed in 17.480s
03:34:38 | DEBUG    | usrbio_utils:usrbio_from_pretrained |    Breakdown: state_dict=17.2s, config=0.2s, model_creation=0.0s
03:34:38 | SUCCESS  | __main__:benchmark_model_loading | ✅ Used direct usrbio sharded loading
03:34:38 | INFO     | __main__:benchmark_model_loading |   Run 1: 17.902s, Memory: +-23.5MB
03:34:38 | DEBUG    | __main__:benchmark_model_loading | 🧹 Cleaned up USRBIO resources for run 1
03:34:38 | INFO     | __main__:benchmark_multiple_models | Average loading time: 17.902s
03:34:38 | INFO     | __main__:benchmark_multiple_models | Average memory usage: +-23.5MB
03:34:38 | SUCCESS  | __main__:benchmark_multiple_models | 🚀 USRBIO acceleration was ACTIVE
03:34:38 | INFO     | __main__:print_summary | 
================================================================================
03:34:38 | INFO     | __main__:print_summary | BENCHMARK SUMMARY
03:34:38 | INFO     | __main__:print_summary | ================================================================================
03:34:38 | INFO     | __main__:print_summary | deepseek-ai/DeepSeek-R1-Distill-Qwen-32B |   17.902s |    -23.5MB |  (🚀 USRBIO DIRECT)
03:34:38 | INFO     | __main__:save_results | 
Results saved to benchmark_results.json
03:34:38 | DEBUG    | usrbio_utils:remove_usrbio_hooks | 🔓 HOOK REMOVED: safetensors.torch.load_file
03:34:38 | DEBUG    | usrbio_utils:remove_usrbio_hooks | 🔓 HOOK REMOVED: torch.load
03:34:38 | INFO     | usrbio_utils:remove_usrbio_hooks | 🔓 USRBIO hooks remov

8 bg threads
se python benchmark.py \
    --drop-caches \
    --hf3fs-mount-point /3fs/stage \
    --cache_dir /3fs/stage/fuse/hf \
    --use-usrbio \
    --direct-sharded-loading \
    --models deepseek-ai/DeepSeek-R1-Distill-Qwen-32B \
    --usrbio-block-size $((1 << 30)) \
    --usrbio-chunk-size $((1 << 30)) \
    --runs 1

FAILED

03:34:01 | INFO     | __main__:benchmark_multiple_models | Average loading time: 22.093s
03:34:01 | INFO     | __main__:benchmark_multiple_models | Average memory usage: +0.5MB
03:34:01 | SUCCESS  | __main__:benchmark_multiple_models | 🚀 USRBIO acceleration was ACTIVE
03:34:01 | INFO     | __main__:print_summary | 
================================================================================
03:34:01 | INFO     | __main__:print_summary | BENCHMARK SUMMARY
03:34:01 | INFO     | __main__:print_summary | ================================================================================
03:34:01 | INFO     | __main__:print_summary | deepseek-ai/DeepSeek-R1-Distill-Qwen-32B |   22.093s |      0.5MB |  (🚀 USRBIO DIRECT)
03:34:01 | INFO     | __main__:save_results | 