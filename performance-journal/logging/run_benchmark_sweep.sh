#!/bin/bash

# KUTrace Logging Benchmark Sweep Example
# This script runs comprehensive benchmark tests and generates plots

set -e

#./build_release/src/benchmark/kutrace_benchmark -t 4 -n 100000 -s 256 -l nanolog -m throughput -d ./test_string_free
# Enable RPC background thread
# export KUTRACE_RPC_USE_BACKGROUND_THREAD=1

# Enable NanoLog background thread  
# export KUTRACE_NANOLOG_USE_BACKGROUND_THREAD=1

# Disable them (any of these work)
# export KUTRACE_RPC_USE_BACKGROUND_THREAD=0
# export KUTRACE_RPC_USE_BACKGROUND_THREAD=false
# unset KUTRACE_RPC_USE_BACKGROUND_THREAD
# Configuration
BINARY_PATH="./build_release/src/benchmark/kutrace_benchmark"
OUTPUT_DIR="/ssd/benchmark_results_$(date +%Y%m%d_%H%M%S)"

echo "KUTrace Logging Benchmark Sweep"
echo "==============================="

# Check if benchmark binary exists
if [[ ! -f "$BINARY_PATH" ]]; then
    echo "Error: Benchmark binary not found at $BINARY_PATH"
    echo "Please build the project first:"
    echo "  mkdir -p build_release && cd build_release"
    echo "  cmake -DCMAKE_BUILD_TYPE=Release .."
    echo "  make -j$(nproc)"
    exit 1
fi

# Check if Python dependencies are installed
if ! python3 -c "import pandas, matplotlib, seaborn, numpy" 2>/dev/null; then
    echo "Installing Python dependencies..."
    pip3 install -r requirements.txt
fi

echo "Running benchmark with binary: $BINARY_PATH"
echo "Output directory: $OUTPUT_DIR"
echo ""

# Run the benchmark sweep
python3 benchmark_runner.py \
    --binary "$BINARY_PATH" \
    --output "$OUTPUT_DIR" \
    --threads 1 2 4 8 16 \
    --operations 50000 100000 200000 \
    --message-sizes 64 256 1024 4096 \
    --loggers both \
    --modes both \
    --verbose

echo ""
echo "Benchmark sweep completed!"
echo "Results and plots are available in: $OUTPUT_DIR"
echo ""
echo "Generated files:"
echo "  - all_results.csv              : Raw benchmark data"
echo "  - throughput_vs_threads.png    : Throughput scaling plot"
echo "  - latency_vs_threads.png       : Latency analysis plot"
echo "  - throughput_vs_message_size.png : Message size impact plot"
echo "  - speedup_heatmap.png          : Performance comparison heatmap"
echo "  - summary_report.txt           : Summary analysis" 