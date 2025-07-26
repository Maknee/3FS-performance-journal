#include <iostream>
#include <string>
#include <vector>
#include <chrono>
#include <thread>
#include <filesystem>
#include <getopt.h>
#include <cstdlib>

#include "benchmark_runner.h"

void print_usage(const char* program_name) {
    std::cout << "Usage: " << program_name << " [OPTIONS]\n"
              << "\nKUTrace RPC Logging Benchmark Tool\n"
              << "\nOPTIONS:\n"
              << "  -h, --help              Show this help message\n"
              << "  -t, --threads NUM       Number of threads (default: 1)\n"
              << "  -d, --directory DIR     Output directory for log files (default: ./logs)\n"
              << "  -n, --operations NUM    Number of operations per thread (default: 10000000)\n"
              << "  -s, --size BYTES        Message size in bytes (default: 64)\n"
              << "  -l, --logger TYPE       Logger type: binary, nanolog, both (default: both)\n"
              << "  -m, --mode MODE         Benchmark mode: latency, throughput, both (default: both)\n"
              << "  -w, --warmup NUM        Number of warmup operations (default: 100000)\n"
              << "  -r, --runs NUM          Number of benchmark runs (default: 3)\n"
              << "  -v, --verbose           Enable verbose output\n"
              << "  --batch-size NUM        Batch size for binary logger (default: 10000)\n"
              << "  --timeout MS            Timeout for binary logger in ms (default: 10)\n"
              << "\nEXAMPLES:\n"
              << "  " << program_name << " -t 4 -n 5000000 -d ./bench_logs\n"
              << "  " << program_name << " -l binary -m latency -t 1 -n 1000000\n"
              << "  " << program_name << " -l nanolog -m throughput -t 8 -s 128\n"
              << std::endl;
}

struct BenchmarkConfig {
    int threads = 1;
    std::string directory = "./logs";
    int operations = 10000000;  // 10M operations for ~5-10 second runtime
    int message_size = 64;
    LoggerType logger_type = LoggerType::Both;
    BenchmarkMode mode = BenchmarkMode::Both;
    int warmup_ops = 100000;    // Increased warmup for better measurements
    int runs = 3;
    bool verbose = false;
    size_t batch_size = 10000;
    size_t timeout_ms = 10;
};

LoggerType parse_logger_type(const std::string& type) {
    if (type == "binary") return LoggerType::Binary;
    else if (type == "nanolog") return LoggerType::NanoLog;
    else if (type == "both") return LoggerType::Both;
    else {
        std::cerr << "Error: Invalid logger type '" << type << "'. Use binary, nanolog, or both." << std::endl;
        exit(1);
    }
}

BenchmarkMode parse_benchmark_mode(const std::string& mode) {
    if (mode == "latency") return BenchmarkMode::Latency;
    else if (mode == "throughput") return BenchmarkMode::Throughput;
    else if (mode == "both") return BenchmarkMode::Both;
    else {
        std::cerr << "Error: Invalid benchmark mode '" << mode << "'. Use latency, throughput, or both." << std::endl;
        exit(1);
    }
}

int main(int argc, char* argv[]) {
    BenchmarkConfig config;
    
    // Long options
    static struct option long_options[] = {
        {"help",       no_argument,       0, 'h'},
        {"threads",    required_argument, 0, 't'},
        {"directory",  required_argument, 0, 'd'},
        {"operations", required_argument, 0, 'n'},
        {"size",       required_argument, 0, 's'},
        {"logger",     required_argument, 0, 'l'},
        {"mode",       required_argument, 0, 'm'},
        {"warmup",     required_argument, 0, 'w'},
        {"runs",       required_argument, 0, 'r'},
        {"verbose",    no_argument,       0, 'v'},
        {"batch-size", required_argument, 0, 1001},
        {"timeout",    required_argument, 0, 1002},
        {0, 0, 0, 0}
    };
    
    int opt;
    int option_index = 0;
    
    while ((opt = getopt_long(argc, argv, "ht:d:n:s:l:m:w:r:v", long_options, &option_index)) != -1) {
        switch (opt) {
            case 'h':
                print_usage(argv[0]);
                return 0;
            case 't':
                config.threads = std::atoi(optarg);
                if (config.threads <= 0) {
                    std::cerr << "Error: Number of threads must be positive." << std::endl;
                    return 1;
                }
                break;
            case 'd':
                config.directory = optarg;
                break;
            case 'n':
                config.operations = std::atoi(optarg);
                if (config.operations <= 0) {
                    std::cerr << "Error: Number of operations must be positive." << std::endl;
                    return 1;
                }
                break;
            case 's':
                config.message_size = std::atoi(optarg);
                if (config.message_size <= 0) {
                    std::cerr << "Error: Message size must be positive." << std::endl;
                    return 1;
                }
                break;
            case 'l':
                config.logger_type = parse_logger_type(optarg);
                break;
            case 'm':
                config.mode = parse_benchmark_mode(optarg);
                break;
            case 'w':
                config.warmup_ops = std::atoi(optarg);
                if (config.warmup_ops < 0) {
                    std::cerr << "Error: Warmup operations must be non-negative." << std::endl;
                    return 1;
                }
                break;
            case 'r':
                config.runs = std::atoi(optarg);
                if (config.runs <= 0) {
                    std::cerr << "Error: Number of runs must be positive." << std::endl;
                    return 1;
                }
                break;
            case 'v':
                config.verbose = true;
                break;
            case 1001: // --batch-size
                config.batch_size = std::atoi(optarg);
                if (config.batch_size <= 0) {
                    std::cerr << "Error: Batch size must be positive." << std::endl;
                    return 1;
                }
                break;
            case 1002: // --timeout
                config.timeout_ms = std::atoi(optarg);
                if (config.timeout_ms <= 0) {
                    std::cerr << "Error: Timeout must be positive." << std::endl;
                    return 1;
                }
                break;
            case '?':
                std::cerr << "Try '" << argv[0] << " --help' for more information." << std::endl;
                return 1;
            default:
                std::cerr << "Error: Unknown option." << std::endl;
                return 1;
        }
    }
    
    // Validate arguments
    if (config.threads > 1000) {
        std::cerr << "Warning: High thread count (" << config.threads << ") may cause issues." << std::endl;
    }
    
    if (config.message_size > 10000) {
        std::cerr << "Warning: Large message size (" << config.message_size << " bytes) may affect performance." << std::endl;
    }
    
    // Create output directory
    try {
        std::filesystem::create_directories(config.directory);
    } catch (const std::exception& e) {
        std::cerr << "Error: Failed to create directory '" << config.directory << "': " << e.what() << std::endl;
        return 1;
    }
    
    // Print configuration
    std::cout << "KUTrace RPC Logging Benchmark\n"
              << "==============================\n"
              << "Threads:        " << config.threads << "\n"
              << "Operations:     " << config.operations << " per thread\n"
              << "Message size:   " << config.message_size << " bytes\n"
              << "Logger type:    ";
    
    switch (config.logger_type) {
        case LoggerType::Binary: std::cout << "Binary"; break;
        case LoggerType::NanoLog: std::cout << "NanoLog"; break;
        case LoggerType::Both: std::cout << "Both"; break;
    }
    
    std::cout << "\nBenchmark mode: ";
    switch (config.mode) {
        case BenchmarkMode::Latency: std::cout << "Latency"; break;
        case BenchmarkMode::Throughput: std::cout << "Throughput"; break;
        case BenchmarkMode::Both: std::cout << "Both"; break;
    }
    
    std::cout << "\nOutput dir:     " << config.directory << "\n"
              << "Warmup ops:     " << config.warmup_ops << "\n"
              << "Runs:           " << config.runs << "\n"
              << "Batch size:     " << config.batch_size << "\n"
              << "Timeout:        " << config.timeout_ms << " ms\n"
              << "Verbose:        " << (config.verbose ? "Yes" : "No") << "\n"
              << std::endl;
    
    // Create and run benchmark
    BenchmarkRunner runner(config.directory, config.verbose);
    
    BenchmarkParams params;
    params.num_threads = config.threads;
    params.operations_per_thread = config.operations;
    params.message_size = config.message_size;
    params.warmup_operations = config.warmup_ops;
    params.num_runs = config.runs;
    params.batch_size = config.batch_size;
    params.timeout_ms = config.timeout_ms;
    
    bool success = true;
    
    try {
        if (config.logger_type == LoggerType::Binary || config.logger_type == LoggerType::Both) {
            std::cout << "Running Binary Logger Benchmarks...\n" << std::endl;
            if (!runner.run_binary_benchmark(params, config.mode)) {
                success = false;
            }
        }
        
        if (config.logger_type == LoggerType::NanoLog || config.logger_type == LoggerType::Both) {
            std::cout << "\nRunning NanoLog Logger Benchmarks...\n" << std::endl;
            if (!runner.run_nanolog_benchmark(params, config.mode)) {
                success = false;
            }
        }
        
        if (config.logger_type == LoggerType::Both) {
            std::cout << "\nRunning Comparison Analysis...\n" << std::endl;
            runner.generate_comparison_report();
        }
        
    } catch (const std::exception& e) {
        std::cerr << "Error during benchmark execution: " << e.what() << std::endl;
        return 1;
    }
    
    if (success) {
        std::cout << "\nBenchmark completed successfully!" << std::endl;
        std::cout << "Results saved to: " << config.directory << std::endl;
        return 0;
    } else {
        std::cerr << "\nBenchmark completed with errors." << std::endl;
        return 1;
    }
} 