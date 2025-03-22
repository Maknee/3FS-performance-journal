# Benchmarks

Benchmark results are stored in [benchmarks](benchmarks/).

# Running the benchmarks

## Pull the json files

```sh
wget https://github.com/kvcache-ai/Mooncake/raw/refs/heads/main/FAST25-release/traces/conversation_trace.jsonl
wget https://github.com/kvcache-ai/Mooncake/raw/refs/heads/main/FAST25-release/traces/synthetic_trace.jsonl
wget https://github.com/kvcache-ai/Mooncake/raw/refs/heads/main/FAST25-release/traces/toolagent_trace.jsonl
```

## Build

Include `libhf3fs_api_shared.so` here. You can find it in the built 3fs folder.

```sh
cmake -DCMAKE_CXX_COMPILER=clang++ -DCMAKE_C_COMPILER=clang -Bbuild -DCMAKE_BUILD_TYPE=RelWithDebInfo
cmake --build build -j
```

## Running

./build/3fs_benchmark --jsonl toolagent_trace.jsonl -l /3fs/stage -o /3fs/stage/fuse/conv.test 
./build/3fs_benchmark --jsonl toolagent_trace.jsonl -l /3fs/stage -o /3fs/stage/fuse/conv.test --mode io_uring
./build/3fs_benchmark --jsonl toolagent_trace.jsonl -o /ssd/conv.test --mode io_uring


./build/3fs_benchmark --jsonl toolagent_trace.jsonl -l /3fs/stage -o /3fs/stage/fuse/conv.test --mode usrbio -k --skip-read
./build/3fs_benchmark --jsonl toolagent_trace.jsonl -l /3fs/stage -o /3fs/stage/fuse/conv.test --mode usrbio -k --skip-write 

./build/3fs_benchmark --jsonl toolagent_trace.jsonl -l /3fs/stage -o /3fs/stage/fuse/conv_70272.test --kv-size 70272 --mode usrbio -k --skip-read
./build/3fs_benchmark --jsonl toolagent_trace.jsonl -l /3fs/stage -o /3fs/stage/fuse/conv_70272.test --kv-size 70272 --mode usrbio -k --skip-write


taskset -c 1 ./build/3fs_benchmark --jsonl toolagent_trace.jsonl -l /3fs/stage -o /3fs/stage/fuse/conv.test -t 1 --mode usrbio -k --skip-read
taskset -c 1 ./build/3fs_benchmark --jsonl toolagent_trace.jsonl -l /3fs/stage -o /3fs/stage/fuse/conv.test -t 1 --mode usrbio -k --skip-write

taskset -c 1 ./build/3fs_benchmark --jsonl toolagent_trace.jsonl -o /3fs/stage/fuse/conv.test --mode io_uring -k --skip-write

taskset -c 1 ./build/3fs_benchmark --jsonl toolagent_trace.jsonl -o /3fs/stage/fuse/conv.test --mode io_uring -k --skip-write -t 1

taskset -c 2,4,6,8 ./build/3fs_benchmark --jsonl toolagent_trace.jsonl -o /3fs/stage/fuse/conv.test --mode io_uring -k --skip-write -t 4

taskset -c 2,4,6,8 ./build/3fs_benchmark --jsonl toolagent_trace.jsonl -o /ssd/conv.test --mode io_uring -k --skip-write -t 4


# Writes
uftrace record -e ./build/3fs_benchmark --jsonl toolagent_trace.jsonl -l /3fs/stage -o /3fs/stage/fuse/conv4.test  --skip-read -m io_uring
uftrace record -N std::* --depth=1024 --max-stack=32384 --kernel-depth=128 --verbose=0 ./build/3fs_benchmark --jsonl toolagent_trace.jsonl -l /3fs/stage -o /3fs/stage/fuse/conv4.test --skip-read -m io_uring
uftrace dump --chrome > writes.trace

uftrace record -N "nholmann::*"  --srcline --max-stack=32384 --kernel-depth=128 -k ./build/3fs_benchmark --jsonl toolagent_trace.jsonl -l /3fs/stage -o /3fs/stage/fuse/conv4.test --skip-read -m io_uring

uftrace record -N "nholmann::*"  --srcline --max-stack=32384 --kernel-depth=128 -k ./build/3fs_benchmark --jsonl toolagent_trace.jsonl -l /3fs/stage -o /3fs/stage/fuse/conv4.test --skip-write -m io_uring