# Personal Notes

## Setup

```sh
go to deploy.py

# Set this if using r650
is_650 = True


device_filter=['mlx5_2']
targets_per_disk=6
file_strip_size = int(targets_per_disk * num_storage_nodes / replication_factor)
# source_dir='/proj/sdcs-PG0/3fs/3FS-performance-journal'
# build_type='build_release'

# FIRST RUN
deploy_3fs_step1()
deploy_3fs_step2()
deploy_3fs_step3()
deploy_3fs_step4()
deploy_3fs_step5()

# SECOND RUN
deploy_3fs_step6(storage_directory_mount_nvme=False)

# THIRD RUN????
deploy_3fs_step7(create_admin_token=True)

# THIRD RUN
source_dir='/proj/sdcs-PG0/3fs/3FS-performance-journal'
deploy_3fs_step8(hf3fs_fuse_main_environment=f'HF3FS_ENABLE_RPC_LOGGING_FILE={source_dir}/log.bin')
```

### Verify if it's working

```sh
sudo mkdir /3fs/stage/fuse
sudo chown -R $USER /3fs/stage/fuse

echo "Test!!!" > /3fs/stage/fuse/aaa

cat /3fs/stage/fuse/aaa

```

### If not working

```sh
echo "list-chains" | /opt/3fs/bin/admin_cli -cfg /opt/3fs/etc/admin_cli.toml

Expected output
ChainId    ReferencedBy  ChainVersion  Status   PreferredOrder  Target                          Target                          Target
900100001  1             1             SERVING  []              101000500101(SERVING-UPTODATE)  101000600101(SERVING-UPTODATE)  101000800101(SERVING-UPTODATE)
900100002  1             1             SERVING  []              101000300101(SERVING-UPTODATE)  101000700101(SERVING-UPTODATE)  101000900101(SERVING-UPTODATE)
900100003  1             1             SERVING  []          
```

```sh

Checking FoundationDB

echo "status" | fdbcli -C /etc/foundationdb/fdb.cluster

Using cluster file `/etc/foundationdb/fdb.cluster'.

The database is available.

Welcome to the fdbcli. For help, type `help'.
fdb> status

Configuration:
  Redundancy mode        - triple
  Storage engine         - ssd-2
  Log engine             - ssd-2
  Encryption at-rest     - disabled
  Coordinators           - 3
  Desired Commit Proxies - 3
  Desired GRV Proxies    - 1

```

```sh
Checking nodes

On client (node-1)

cat /var/log/3fs/hf3fs_fuse_main.log
cat /var/log/3fs/hf3fs_fuse_main-err.log

sudo systemctl status hf3fs_fuse_main.service
sudo journalctl -u hf3fs_fuse_main -e
sudo journalctl -u hf3fs_fuse_main --no-pager
sudo journalctl -u hf3fs_fuse_main -f

On mgmtd/meta (node-0)

cat /var/log/3fs/hf3fs_meta_main.log

sudo systemctl status mgmtd_main
sudo journalctl -u mgmtd_main -e

sudo systemctl status meta_main
sudo journalctl -u meta_main -e

On storage (node-2 -> node-X)

sudo systemctl status storage_main
sudo journalctl -u storage_main -e

```

## Running benchmarks

```sh
If needed, re-adjust buffer size for kutrace on the node that you use

cd /proj/sdcs-PG0/3fs/3FS-performance-journal/KUtrace/linux/setup/module
sudo rmmod -f kutrace_mod.ko
sudo insmod kutrace_mod.ko tracemb=100 check=0


Terminal 1
rm *.trace *.json *.html


cd /proj/sdcs-PG0/3fs/3FS-performance-journal/KUtrace/linux/setup/postproc
watchexec --emit-events-to=json-stdio --only-emit-events --debounce 5s --postpone -w "/proj/sdcs-PG0/3fs/3FS-performance-journal/performance-journal/kv" -e trace | jq -r --unbuffered 'select(.tags[] | .kind == "fs" and .simple == "create") | .tags[] | select(.kind=="path") | .absolute' | xargs -I{} ./postproc3.sh {}


Terminal 2

cd /proj/sdcs-PG0/3fs/3FS-performance-journal/performance-journal/kv
miniserve -p 8082

On google-chrome go to http://localhost:8082/ and browse
```

## Profiling

```sh
cd /proj/sdcs-PG0/3fs/3FS-performance-journal/
cp dumplogfile4 /proj/sdcs-PG0/3fs/3FS-performance-journal
cp d3.v4.min.js /proj/sdcs-PG0/3fs/3FS-performance-journal
cp show_rpc.html /proj/sdcs-PG0/3fs/3FS-performance-journal

cd /proj/sdcs-PG0/3fs/3FS-performance-journal
./dumplogfile4 -req "Benchmarking 3FS" log.bin > log.json
./makeself show_rpc.html log.json /proj/sdcs-PG0/3fs/3FS-performance-journal/performance-journal/kv/log.html

./makeself show_rpc.html log.json log.html


```

## Building 3fs local without tests

```sh
cmake --build build -j -t hf3fs_fuse_main
```

```sh
cp build/_deps/nanolog-build/decompressor .
./decompressor decompress /ssd/nanolog.bin  
./decompressor decompressJson /ssd/nanolog.bin --pretty
```


