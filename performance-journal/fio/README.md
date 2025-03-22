# Benchmarks

Benchmark results are stored in [benchmarks](benchmarks/).

# Running the benchmarks

## Pull the json files

```sh
pip install fio-plot
```

## Configuration

Modify the benchmark_3fs_4k.ini to your setup. The main files to change are:

```sh
target = /3fs/stage/fuse/iouring # Point the directory to somwhere in the 3fs fuse directory
block_size = 1M # Configure the block size to be 4k, 1M or 4M
engine = external:/3fs/benchmarks/fio_usrbio/hf3fs_usrbio.so # Point the engine to the usrbio shared object
extra_opts = mountpoint=/3fs/stage/,ior_depth=0,ior_timeout=1 # Set mountpoint to the 3fs fuse directory, this needs to be visible to the usrbio engine
```

## Running

```sh
bench-fio benchmark_3fs_4k.ini
```

## Generating fio plots

```sh
fio-plot -i benchmarks/ssd/4k_ssd_xfs_iouring_xl170_1/4k -o 4k_ssd_xfs_iouring_xl170_1_bw_read.png -T '4K Thread Scaling (qd=128)' -s https://maknee.github.io -r read -d 1 2 4 8 16 32 64 128 -n 1 2 4 8 -M 128 -J 64 -D 200 -p 50.0 --title-fontsize 16 --subtitle-fontsize 12 --source-fontsize 10 --disable-grid --disable-fio-version --enable-markers --bargraph3d -t bw
fio-plot -i benchmarks/ssd/4k_ssd_xfs_iouring_xl170_1/4k -o 4k_ssd_xfs_iouring_xl170_1_lat_read.png -T '4K Thread Scaling (qd=128)' -s https://maknee.github.io -r read -d 1 2 4 8 16 32 64 128 -n 1 2 4 8 -M 128 -J 64 -D 200 -p 50.0 --title-fontsize 16 --subtitle-fontsize 12 --source-fontsize 10 --disable-grid --disable-fio-version --enable-markers --bargraph3d -t lat

```