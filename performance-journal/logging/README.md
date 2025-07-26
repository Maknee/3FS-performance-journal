# KUTrace RPC Logger

A high-performance, header-only C++ library for logging RPC (Remote Procedure Call) transactions with microsecond precision timing. This library provides both binary and text-based logging options and includes comprehensive benchmarking tools.

## Features

- **Dual Logging Modes**: Binary logging for maximum performance, NanoLog integration for structured text logging
- **Microsecond Precision**: Accurate timestamp recording using `gettimeofday()`
- **Thread-Safe**: Background worker threads for asynchronous logging without blocking main execution
- **Zero-Copy Design**: Minimal memory allocation during logging operations
- **Comprehensive Benchmarking**: Built-in latency and throughput measurement tools
- **Report Generation**: Automatic CSV and JSON report generation from binary logs
- **Header-Only**: Easy integration with minimal dependencies

## Quick Start

### Prerequisites

- C++20 compatible compiler (GCC 10+, Clang 12+)
- CMake 3.16+
- POSIX-compliant system (Linux, macOS)

### Building

```bash
# Clone and build
cd performance-journal
mkdir build && cd build
cmake ..
make -j$(nproc)

# Run simple example
./simple_example

# Run benchmarks
./kutrace_benchmark --help
```

## Project Structure

```
performance-journal/
├── CMakeLists.txt                    # Main CMake configuration
├── README.md                         # This file
├── src/
│   ├── include/
│   │   └── kutrace_logger.h          # Main header file
│   ├── benchmark/
│   │   ├── CMakeLists.txt           # Benchmark CMake config
│   │   ├── main.cpp                 # Benchmark CLI tool
│   │   ├── benchmark_runner.h       # Benchmark framework
│   │   └── benchmark_runner.cpp     # Benchmark implementation
│   ├── simple_example.cpp           # Basic usage example
│   └── third_party/
│       ├── concurrentqueue/         # Lock-free queue (auto-downloaded)
│       └── nanolog/                 # Mock NanoLog implementation
```

## Usage Examples

### Basic RPC Logging

```cpp
#include "kutrace_logger.h"

// Create logger
kutrace::RPCLogger logger("rpc_trace.bin");

// Define network endpoints
kutrace::NetworkAddress client("127.0.0.1", 8080);
kutrace::NetworkAddress server("127.0.0.1", 9090);
kutrace::RPCMessage request("Hello, Server!");

// Log client sending request
auto req_time = logger.log_client_send(
    1001, 0, client, server, "echo", request);

// ... RPC happens ...

// Log client receiving response
kutrace::RPCMessage response("Hello, Client!");
logger.log_client_recv(
    1001, 0, client, server, "echo", 
    kutrace::RPCStatus::Success, response,
    req_time, req_rcv_time, resp_send_time);
```

### Benchmark Usage

```bash
# Basic benchmark with 4 threads, 10k operations each
./kutrace_benchmark -t 4 -n 10000 -d ./results

# Latency-focused test with binary logger only
./kutrace_benchmark -l binary -m latency -t 1 -n 50000

# Throughput test with both loggers
./kutrace_benchmark -l both -m throughput -t 8 -s 128 -v

# Custom parameters
./kutrace_benchmark \
  --threads 16 \
  --operations 100000 \
  --size 256 \
  --directory ./bench_results \
  --logger both \
  --mode both \
  --verbose
```

### Benchmark Options

| Option | Description | Default |
|--------|-------------|---------|
| `-t, --threads` | Number of concurrent threads | 1 |
| `-d, --directory` | Output directory for logs/results | ./logs |
| `-n, --operations` | Operations per thread | 100000 |
| `-s, --size` | Message size in bytes | 64 |
| `-l, --logger` | Logger type: `binary`, `nanolog`, `both` | both |
| `-m, --mode` | Benchmark mode: `latency`, `throughput`, `both` | both |
| `-w, --warmup` | Warmup operations | 1000 |
| `-r, --runs` | Number of benchmark runs | 3 |
| `-v, --verbose` | Enable verbose output | false |
| `--batch-size` | Binary logger batch size | 10000 |
| `--timeout` | Binary logger timeout (ms) | 10 |

## Performance Characteristics

### Binary Logger
- **Latency**: ~100-500 nanoseconds per log entry
- **Throughput**: 2-10 million operations/second (depending on hardware)
- **Memory**: Fixed 96-byte records, configurable batching
- **Persistence**: Immediate binary write with background flushing

### NanoLog Logger  
- **Latency**: ~200-1000 nanoseconds per log entry
- **Throughput**: 1-5 million operations/second
- **Memory**: Compressed text format with efficient serialization
- **Persistence**: Asynchronous with automatic compression

## Benchmark Results Interpretation

### Latency Metrics
- **Average**: Mean time per logging operation
- **P50/P95/P99**: Percentile latencies (50th, 95th, 99th percentile)
- **Min/Max**: Best and worst case latencies

### Throughput Metrics  
- **Operations/second**: Total logging rate across all threads
- **Scalability**: How performance changes with thread count

### Example Output
```
=== Binary Logger - Latency Results ===
Threads:           4
Total Operations:  400000
Duration:          0.842 seconds
Throughput:        475059.38 ops/sec
Average Latency:   0.234 μs
P50 Latency:       0.198 μs
P95 Latency:       0.387 μs
P99 Latency:       0.842 μs
```

## Advanced Configuration

### Environment Variables

```bash
# Enable global RPC logging to file
export HF3FS_ENABLE_RPC_LOGGING_FILE="/tmp/global_rpc.bin"

# Enable NanoLog global logging
export HF3FS_ENABLE_RPC_NANOLOG_FILE="/tmp/global_nano.log"
```

### Custom Build Options

```bash
# Build with Folly support (if available)
cmake -DHAVE_FOLLY=ON ..

# Debug build with additional checks
cmake -DCMAKE_BUILD_TYPE=Debug ..

# Optimized release build
cmake -DCMAKE_BUILD_TYPE=Release -DCMAKE_CXX_FLAGS="-march=native" ..
```

## Dependencies

### Required (auto-managed)
- **concurrentqueue**: Lock-free queue for background logging
- **pthread**: POSIX threads for worker threads

### Optional
- **Folly**: Facebook's C++ library (advanced features)
- **NanoLog**: High-performance logging library (can use mock version)

## Integration Guide

### CMake Integration

```cmake
find_package(kutrace_logger REQUIRED)
target_link_libraries(your_target PRIVATE kutrace::kutrace_logger)
```

### Header-Only Usage

```cpp
// Copy kutrace_logger.h to your project
#include "kutrace_logger.h"

// Link against pthread
// g++ your_code.cpp -pthread
```

## Report Generation

### CSV Reports
```cpp
kutrace::RPCLogger::generate_text_report("trace.bin", "report.csv");
```

### JSON Reports (for visualization)
```cpp
kutrace::RPCLogger::generate_json_report("trace.bin", "trace.json", "My RPC Trace");
```

## Troubleshooting

### Common Issues

1. **Compilation errors**: Ensure C++20 support and pthread linking
2. **High latency**: Check system load and disk I/O performance  
3. **Memory usage**: Adjust batch sizes and timeout values
4. **Missing symbols**: Verify all dependencies are properly linked

### Performance Tuning

```cpp
// Increase batch size for higher throughput
logger.open("trace.bin", 50000, 50);

// Reduce batch size for lower latency
logger.open("trace.bin", 1000, 1);
```

## Contributing

1. Fork the repository
2. Create feature branch (`git checkout -b feature/amazing-feature`)
3. Commit changes (`git commit -m 'Add amazing feature'`)
4. Push to branch (`git push origin feature/amazing-feature`)
5. Open Pull Request

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Acknowledgments

- Inspired by Google's KUTrace kernel tracing system
- Uses Cameron314's concurrent queue for lock-free logging
- NanoLog integration for high-performance text logging
