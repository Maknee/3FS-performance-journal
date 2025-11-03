# Checkpoint Writing Benchmark

A comprehensive benchmark for measuring Hugging Face model checkpoint writing performance using different methods and configurations.

## Features

- **Model Caching**: Downloads and caches models in a specified directory
- **Checkpoint Writing**: Saves checkpoints to a separate directory using multiple methods
- **Performance Metrics**: Measures time, file size, CPU usage, memory usage, and disk I/O
- **Statistical Analysis**: Computes statistics across multiple iterations
- **Multiple Save Methods**: Tests three different checkpoint saving approaches:
  - Manual save using `save_pretrained()`
  - PyTorch save using `torch.save()`
  - Trainer save using Hugging Face `Trainer.save_model()`

## Installation

```bash
pip install -r requirements.txt
```

## Usage

### Basic Usage

```bash
python benchmark.py
```

This will use default settings:
- Model: `bert-base-uncased`
- Cache directory: `./cache`
- Checkpoint directory: `./checkpoints`
- Iterations: 3

### Custom Configuration

```bash
python benchmark.py \
    --model "distilbert-base-uncased" \
    --cache-dir "/path/to/cache" \
    --checkpoint-dir "/path/to/checkpoints" \
    --iterations 5 \
    --cleanup
```

### Available Options

- `--model`: Hugging Face model name (default: `bert-base-uncased`)
- `--cache-dir`: Directory for caching downloaded models (default: `./cache`)
- `--checkpoint-dir`: Directory for writing checkpoints (default: `./checkpoints`)
- `--iterations`: Number of benchmark iterations (default: 3)
- `--cleanup`: Clean up checkpoints after benchmark
- `--save-results`: Save results to JSON file (default: True)

## Output

The benchmark will output:
1. **Real-time progress**: Shows each method's performance as it runs
2. **Summary statistics**: Average times, standard deviations, file sizes
3. **JSON results file**: Detailed results saved to `benchmark_results.json`

### Example Output

```
Checkpoint Writing Benchmark
========================================
Model: bert-base-uncased
Cache Directory: ./cache
Checkpoint Directory: ./checkpoints
Iterations: 3

Loading model bert-base-uncased with cache_dir: ./cache
Model loaded in 2.34 seconds

Running benchmark suite with 3 iterations...

--- Iteration 1/3 ---
Testing manual_save...
  Time: 1.23s, Size: 440.2MB
Testing torch_save...
  Time: 0.87s, Size: 438.1MB
Testing trainer_save...
  Time: 1.45s, Size: 440.2MB

================================================================================
CHECKPOINT WRITING BENCHMARK RESULTS
================================================================================
Model: bert-base-uncased
Cache Directory: ./cache
Checkpoint Directory: ./checkpoints

Method: manual_save_pretrained
  Average Time: 1.234 ± 0.056 seconds
  Time Range: 1.178 - 1.290 seconds
  Average Size: 440.2 ± 0.1 MB
  Iterations: 3

Method: torch_save
  Average Time: 0.876 ± 0.032 seconds
  Time Range: 0.844 - 0.908 seconds
  Average Size: 438.1 ± 0.0 MB
  Iterations: 3

Method: trainer_save
  Average Time: 1.456 ± 0.089 seconds
  Time Range: 1.367 - 1.545 seconds
  Average Size: 440.2 ± 0.1 MB
  Iterations: 3
```

## Tested Models

The benchmark works with any Hugging Face model, but here are some popular options:

- `bert-base-uncased` (110M parameters)
- `distilbert-base-uncased` (66M parameters)
- `roberta-base` (125M parameters)
- `gpt2` (117M parameters)
- `microsoft/DialoGPT-medium` (345M parameters)

## Directory Structure

After running the benchmark:

```
checkpoint_writing/
├── benchmark.py           # Main benchmark script
├── requirements.txt       # Python dependencies
├── README.md             # This file
├── cache/                # Model cache directory
│   └── models--bert-base-uncased/
├── checkpoints/          # Checkpoint output directory
│   ├── manual_save_iter_0/
│   ├── torch_save_iter_0.pt
│   ├── trainer_trainer_save_iter_0/
│   └── benchmark_results.json
```

## Performance Considerations

- **Cache Directory**: First run will download the model, subsequent runs will use cached version
- **Disk Space**: Ensure sufficient space for model cache + multiple checkpoint copies
- **Memory**: Larger models require more RAM for loading and checkpoint writing
- **I/O Performance**: Checkpoint writing performance depends heavily on disk I/O speed

## Extending the Benchmark

You can easily extend the benchmark by:

1. Adding new checkpoint saving methods to the `CheckpointWritingBenchmark` class
2. Adding new metrics to the `measure_system_resources()` method
3. Testing different model configurations or sizes
4. Adding compression or optimization techniques 