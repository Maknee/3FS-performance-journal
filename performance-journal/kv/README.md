# Pull the json files

```sh
wget https://github.com/kvcache-ai/Mooncake/raw/refs/heads/main/FAST25-release/traces/conversation_trace.jsonl
wget https://github.com/kvcache-ai/Mooncake/raw/refs/heads/main/FAST25-release/traces/synthetic_trace.jsonl
wget https://github.com/kvcache-ai/Mooncake/raw/refs/heads/main/FAST25-release/traces/toolagent_trace.jsonl
```

# Build

cmake -DCMAKE_CXX_COMPILER=clang++ -DCMAKE_C_COMPILER=clang -Bbuild -DCMAKE_BUILD_TYPE=RelWithDebInfo
cmake --build build -j

# Run

./build/3fs_benchmark --jsonl toolagent_trace.jsonl -l /3fs/stage -o /3fs/stage/fuse/conv.test 
./build/3fs_benchmark --jsonl toolagent_trace.jsonl -l /3fs/stage -o /3fs/stage/fuse/conv.test --mode io_uring
./build/3fs_benchmark --jsonl toolagent_trace.jsonl -o /ssd/conv.test --mode io_uring

sudo mkdir -p /3fs/stage/fuse/
sudo chown -R makneee /3fs/stage/fuse/

./build/3fs_benchmark --jsonl toolagent_trace.jsonl -l /3fs/stage -o /3fs/stage/fuse/conv.test --mode usrbio --kutrace-resolve-symbols -k --skip-read
./build/3fs_benchmark --jsonl toolagent_trace.jsonl -l /3fs/stage -o /3fs/stage/fuse/conv.test --mode usrbio -k --skip-write 

./build/3fs_benchmark --jsonl toolagent_trace.jsonl -l /3fs/stage -o /3fs/stage/fuse/conv_70272.test --kv-size 70272 --mode usrbio -k --skip-read
./build/3fs_benchmark --jsonl toolagent_trace.jsonl -l /3fs/stage -o /3fs/stage/fuse/conv_70272.test --kv-size 70272 --mode usrbio -k --skip-write

./build/3fs_benchmark --jsonl toolagent_trace.jsonl -o /ssd/conv_iouring_512.test --kv-size 512 --mode io_uring -k --skip-read
./build/3fs_benchmark --jsonl toolagent_trace.jsonl -o /ssd/conv_iouring_512.test --kv-size 512 --mode io_uring -k --skip-write

./build/3fs_benchmark --jsonl toolagent_trace.jsonl -o /ssd/conv_iouring_70272.test --kv-size 70272 --mode io_uring -k --skip-read
./build/3fs_benchmark --jsonl toolagent_trace.jsonl -o /ssd/conv_iouring_70272.test --kv-size 70272 --mode io_uring -k --skip-write

./build/3fs_benchmark --jsonl toolagent_trace.jsonl -o /ssd/conv_libc_512.test --kv-size 512 --mode libc -k --skip-read
./build/3fs_benchmark --jsonl toolagent_trace.jsonl -o /ssd/conv_libc_512.test --kv-size 512 --mode libc -k --skip-write

./build/3fs_benchmark --jsonl toolagent_trace.jsonl -o /ssd/conv_libc_70272.test --kv-size 70272 --mode libc -k --skip-read
./build/3fs_benchmark --jsonl toolagent_trace.jsonl -o /ssd/conv_libc_70272.test --kv-size 70272 --mode libc -k --skip-write

./build/3fs_benchmark --jsonl toolagent_trace.jsonl -l /3fs/stage -o /3fs/stage/fuse/conv_iouring_512.test --kv-size 512 --mode io_uring -k --skip-read
./build/3fs_benchmark --jsonl toolagent_trace.jsonl -l /3fs/stage -o /3fs/stage/fuse/conv_iouring_512.test --kv-size 512 --mode io_uring -k --skip-write

./build/3fs_benchmark --jsonl toolagent_trace.jsonl -l /3fs/stage -o /3fs/stage/fuse/conv_iouring_70272.test --kv-size 70272 --mode io_uring -k --skip-read
./build/3fs_benchmark --jsonl toolagent_trace.jsonl -l /3fs/stage -o /3fs/stage/fuse/conv_iouring_70272.test --kv-size 70272 --mode io_uring -k --skip-write

./build/3fs_benchmark --jsonl toolagent_trace.jsonl -l /3fs/stage -o /3fs/stage/fuse/conv_libc_512.test --kv-size 512 --mode libc -k --skip-read
./build/3fs_benchmark --jsonl toolagent_trace.jsonl -l /3fs/stage -o /3fs/stage/fuse/conv_libc_512.test --kv-size 512 --mode libc -k --skip-write

./build/3fs_benchmark --jsonl toolagent_trace.jsonl -l /3fs/stage -o /3fs/stage/fuse/conv_libc_70272.test --kv-size 70272 --mode libc -k --skip-read
./build/3fs_benchmark --jsonl toolagent_trace.jsonl -l /3fs/stage -o /3fs/stage/fuse/conv_libc_70272.test --kv-size 70272 --mode libc -k --skip-write

taskset -c 96,97,98,99 ./build/3fs_benchmark --jsonl toolagent_trace.jsonl -l /3fs/stage -o /3fs/stage/fuse/conv.test -t 4 --mode usrbio -k --skip-read
taskset -c 96,97,98,99 ./build/3fs_benchmark --jsonl toolagent_trace.jsonl -l /3fs/stage -o /3fs/stage/fuse/conv.test -t 4 --mode usrbio -k --skip-write 

taskset -c 96,97,98,99 ./build/3fs_benchmark --jsonl toolagent_trace.jsonl -l /3fs/stage -o /3fs/stage/fuse/conv_70272.test -t 4 --kv-size 70272 --mode usrbio -k --skip-read
taskset -c 96,97,98,99 ./build/3fs_benchmark --jsonl toolagent_trace.jsonl -l /3fs/stage -o /3fs/stage/fuse/conv_70272.test -t 4 --kv-size 70272 --mode usrbio -k --skip-write

taskset -c 96,97,98,99 ./build/3fs_benchmark --jsonl toolagent_trace.jsonl -o /ssd/conv_iouring_512.test -t 4 --kv-size 512 --mode io_uring -k --skip-read
taskset -c 96,97,98,99 ./build/3fs_benchmark --jsonl toolagent_trace.jsonl -o /ssd/conv_iouring_512.test -t 4 --kv-size 512 --mode io_uring -k --skip-write

taskset -c 96,97,98,99 ./build/3fs_benchmark --jsonl toolagent_trace.jsonl -o /ssd/conv_iouring_70272.test -t 4 --kv-size 70272 --mode io_uring -k --skip-read
taskset -c 96,97,98,99 ./build/3fs_benchmark --jsonl toolagent_trace.jsonl -o /ssd/conv_iouring_70272.test -t 4 --kv-size 70272 --mode io_uring -k --skip-write

taskset -c 96,97,98,99 ./build/3fs_benchmark --jsonl toolagent_trace.jsonl -o /ssd/conv_libc_512.test -t 4 --kv-size 512 --mode libc -k --skip-read
taskset -c 96,97,98,99 ./build/3fs_benchmark --jsonl toolagent_trace.jsonl -o /ssd/conv_libc_512.test -t 4 --kv-size 512 --mode libc -k --skip-write

taskset -c 96,97,98,99 ./build/3fs_benchmark --jsonl toolagent_trace.jsonl -o /ssd/conv_libc_70272.test -t 4 --kv-size 70272 --mode libc -k --skip-read
taskset -c 96,97,98,99 ./build/3fs_benchmark --jsonl toolagent_trace.jsonl -o /ssd/conv_libc_70272.test -t 4 --kv-size 70272 --mode libc -k --skip-write

taskset -c 96,97,98,99 ./build/3fs_benchmark --jsonl toolagent_trace.jsonl -l /3fs/stage -o /3fs/stage/fuse/conv_iouring_512.test -t 4 --kv-size 512 --mode io_uring -k --skip-read
taskset -c 96,97,98,99 ./build/3fs_benchmark --jsonl toolagent_trace.jsonl -l /3fs/stage -o /3fs/stage/fuse/conv_iouring_512.test -t 4 --kv-size 512 --mode io_uring -k --skip-write

taskset -c 96,97,98,99 ./build/3fs_benchmark --jsonl toolagent_trace.jsonl -l /3fs/stage -o /3fs/stage/fuse/conv_iouring_70272.test -t 4 --kv-size 70272 --mode io_uring -k --skip-read
taskset -c 96,97,98,99 ./build/3fs_benchmark --jsonl toolagent_trace.jsonl -l /3fs/stage -o /3fs/stage/fuse/conv_iouring_70272.test -t 4 --kv-size 70272 --mode io_uring -k --skip-write

taskset -c 96,97,98,99 ./build/3fs_benchmark --jsonl toolagent_trace.jsonl -l /3fs/stage -o /3fs/stage/fuse/conv_libc_512.test -t 4 --kv-size 512 --mode libc -k --skip-read
taskset -c 96,97,98,99 ./build/3fs_benchmark --jsonl toolagent_trace.jsonl -l /3fs/stage -o /3fs/stage/fuse/conv_libc_512.test -t 4 --kv-size 512 --mode libc -k --skip-write

taskset -c 96,97,98,99 ./build/3fs_benchmark --jsonl toolagent_trace.jsonl -l /3fs/stage -o /3fs/stage/fuse/conv_libc_70272.test -t 4 --kv-size 70272 --mode libc -k --skip-read
taskset -c 96,97,98,99 ./build/3fs_benchmark --jsonl toolagent_trace.jsonl -l /3fs/stage -o /3fs/stage/fuse/conv_libc_70272.test -t 4 --kv-size 70272 --mode libc -k --skip-write


taskset -c 96 ./build/3fs_benchmark --jsonl toolagent_trace.jsonl -l /3fs/stage -o /3fs/stage/fuse/conv.test -t 1 --mode usrbio -k --skip-read
taskset -c 96 ./build/3fs_benchmark --jsonl toolagent_trace.jsonl -l /3fs/stage -o /3fs/stage/fuse/conv.test -t 1 --mode usrbio -k --skip-write

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