#include "benchmark_runner.h"
#include "../include/kutrace_logger.h"

#ifdef KUTRACE_NANOLOG_ENABLE
#include "NanoLogCpp17.h"
#endif

#include <iostream>
#include <iomanip>
#include <sstream>
#include <fstream>
#include <thread>
#include <random>
#include <algorithm>
#include <atomic>
#include <barrier>
#include <chrono>
#include <filesystem>
#include <cstdlib>

using namespace std::chrono;

BenchmarkRunner::BenchmarkRunner(const std::string& output_dir, bool verbose)
    : output_dir_(output_dir), verbose_(verbose) {
    // Ensure output directory exists
    std::filesystem::create_directories(output_dir_);
    
    // Set environment variables for global logger instances
    std::string global_binary_file = output_dir_ + "/global_binary_logger.bin";
    std::string global_nanolog_file = output_dir_ + "/global_nanolog_logger.log";
    
    // Set environment variables so the global logger instances work
    setenv("HF3FS_ENABLE_RPC_LOGGING_FILE", global_binary_file.c_str(), 1);
    setenv("HF3FS_ENABLE_RPC_NANOLOG_FILE", global_nanolog_file.c_str(), 1);
    
    if (verbose_) {
        std::cout << "Set global binary logger file: " << global_binary_file << std::endl;
        std::cout << "Set global nanolog logger file: " << global_nanolog_file << std::endl;
    }
}

BenchmarkRunner::~BenchmarkRunner() = default;

bool BenchmarkRunner::run_binary_benchmark(const BenchmarkParams& params, BenchmarkMode mode) {
    bool success = true;
    
    if (mode == BenchmarkMode::Latency || mode == BenchmarkMode::Both) {
        if (verbose_) std::cout << "Running Binary Logger Latency Benchmark..." << std::endl;
        auto result = run_latency_benchmark_binary(params);
        results_.push_back(result);
        print_results(result);
        save_results_to_file(result, output_dir_ + "/binary_latency_results.csv");
        save_latency_samples(result, output_dir_ + "/binary_latency_samples.csv");
    }
    
    if (mode == BenchmarkMode::Throughput || mode == BenchmarkMode::Both) {
        if (verbose_) std::cout << "Running Binary Logger Throughput Benchmark..." << std::endl;
        auto result = run_throughput_benchmark_binary(params);
        results_.push_back(result);
        print_results(result);
        save_results_to_file(result, output_dir_ + "/binary_throughput_results.csv");
    }
    
    return success;
}

bool BenchmarkRunner::run_nanolog_benchmark(const BenchmarkParams& params, BenchmarkMode mode) {
    bool success = true;
    
    if (mode == BenchmarkMode::Latency || mode == BenchmarkMode::Both) {
        if (verbose_) std::cout << "Running NanoLog Logger Latency Benchmark..." << std::endl;
        auto result = run_latency_benchmark_nanolog(params);
        results_.push_back(result);
        print_results(result);
        save_results_to_file(result, output_dir_ + "/nanolog_latency_results.csv");
        save_latency_samples(result, output_dir_ + "/nanolog_latency_samples.csv");
    }
    
    if (mode == BenchmarkMode::Throughput || mode == BenchmarkMode::Both) {
        if (verbose_) std::cout << "Running NanoLog Logger Throughput Benchmark..." << std::endl;
        auto result = run_throughput_benchmark_nanolog(params);
        results_.push_back(result);
        print_results(result);
        save_results_to_file(result, output_dir_ + "/nanolog_throughput_results.csv");
    }
    
    return success;
}

BenchmarkResults BenchmarkRunner::run_latency_benchmark_binary(const BenchmarkParams& params) {
    BenchmarkResults result;
    result.logger_name = "Binary Logger";
    result.mode_name = "Latency";
    result.num_threads = params.num_threads;
    result.total_operations = params.num_threads * params.operations_per_thread;
    
    // Create logger
    std::string log_file = output_dir_ + "/binary_latency_" + get_timestamp_string() + ".bin";
    kutrace::RPCLogger logger(log_file);
    
    if (!logger.is_ready()) {
        std::cerr << "Failed to initialize binary logger" << std::endl;
        return result;
    }
    
    // Thread synchronization
    std::vector<std::thread> threads;
    std::vector<std::vector<double>> thread_latencies(params.num_threads);
    
    // Use a simple counter-based barrier for compatibility
    std::atomic<int> ready_count{0};
    std::atomic<bool> start_flag{false};
    
    auto start_time = high_resolution_clock::now();
    
    // Launch threads
    for (int i = 0; i < params.num_threads; ++i) {
        threads.emplace_back([this, i, &params, &thread_latencies, &ready_count, &start_flag]() {
            try {
                // Wait for all threads to be ready
                ready_count.fetch_add(1);
                while (!start_flag.load()) {
                    std::this_thread::yield();
                }
                
                binary_logger_worker(i, params, thread_latencies[i], true);
            } catch (const std::exception& e) {
                std::cerr << "Exception in binary logger worker thread " << i << ": " << e.what() << std::endl;
            } catch (...) {
                std::cerr << "Unknown exception in binary logger worker thread " << i << std::endl;
            }
        });
    }
    
    // Wait for all threads to be ready, then start
    while (ready_count.load() < params.num_threads) {
        std::this_thread::yield();
    }
    start_flag.store(true);
    
    // Wait for completion
    for (auto& t : threads) {
        t.join();
    }
    
    auto end_time = high_resolution_clock::now();
    result.duration_seconds = duration_cast<microseconds>(end_time - start_time).count() / 1000000.0;
    
    // Merge latency samples
    for (const auto& latencies : thread_latencies) {
        result.latency_samples.insert(result.latency_samples.end(), latencies.begin(), latencies.end());
    }
    
    calculate_latency_stats(result);
    result.operations_per_second = result.total_operations / result.duration_seconds;
    
    return result;
}

BenchmarkResults BenchmarkRunner::run_throughput_benchmark_binary(const BenchmarkParams& params) {
    BenchmarkResults result;
    result.logger_name = "Binary Logger";
    result.mode_name = "Throughput";
    result.num_threads = params.num_threads;
    result.total_operations = params.num_threads * params.operations_per_thread;
    
    // Create logger
    std::string log_file = output_dir_ + "/binary_throughput_" + get_timestamp_string() + ".bin";
    kutrace::RPCLogger logger(log_file);
    
    if (!logger.is_ready()) {
        std::cerr << "Failed to initialize binary logger" << std::endl;
        return result;
    }
    
    // Thread synchronization
    std::vector<std::thread> threads;
    std::vector<std::vector<double>> thread_latencies(params.num_threads);
    
    std::atomic<int> ready_count{0};
    std::atomic<bool> start_flag{false};
    
    auto start_time = high_resolution_clock::now();
    
    // Launch threads
    for (int i = 0; i < params.num_threads; ++i) {
        threads.emplace_back([this, i, &params, &thread_latencies, &ready_count, &start_flag]() {
            try {
                ready_count.fetch_add(1);
                while (!start_flag.load()) {
                    std::this_thread::yield();
                }
                
                binary_logger_worker(i, params, thread_latencies[i], false);
            } catch (const std::exception& e) {
                std::cerr << "Exception in binary logger throughput worker thread " << i << ": " << e.what() << std::endl;
            } catch (...) {
                std::cerr << "Unknown exception in binary logger throughput worker thread " << i << std::endl;
            }
        });
    }
    
    // Wait for all threads to be ready, then start
    while (ready_count.load() < params.num_threads) {
        std::this_thread::yield();
    }
    start_flag.store(true);
    
    // Wait for completion
    for (auto& t : threads) {
        t.join();
    }
    
    auto end_time = high_resolution_clock::now();
    result.duration_seconds = duration_cast<microseconds>(end_time - start_time).count() / 1000000.0;
    result.operations_per_second = result.total_operations / result.duration_seconds;
    
    return result;
}

BenchmarkResults BenchmarkRunner::run_latency_benchmark_nanolog(const BenchmarkParams& params) {
    BenchmarkResults result;
    result.logger_name = "NanoLog Logger";
    result.mode_name = "Latency";
    result.num_threads = params.num_threads;
    result.total_operations = params.num_threads * params.operations_per_thread;
    
    // Ensure the global logger is initialized by getting it first
    auto* global_logger = kutrace::RPCNanoLogger::get();
    if (!global_logger || !global_logger->is_ready()) {
        std::cerr << "Failed to initialize global nanolog logger" << std::endl;
        return result;
    }
    
    // Thread synchronization
    std::vector<std::thread> threads;
    std::vector<std::vector<double>> thread_latencies(params.num_threads);
    
    std::atomic<int> ready_count{0};
    std::atomic<bool> start_flag{false};
    
    auto start_time = high_resolution_clock::now();

    // Launch threads
    for (int i = 0; i < params.num_threads; ++i) {
        threads.emplace_back([this, i, &params, &thread_latencies, &ready_count, &start_flag]() {
            try {
                ready_count.fetch_add(1);
                while (!start_flag.load()) {
                    std::this_thread::yield();
                }
                
                nanolog_worker(i, params, thread_latencies[i], true);
            } catch (const std::exception& e) {
                std::cerr << "Exception in nanolog latency worker thread " << i << ": " << e.what() << std::endl;
            } catch (...) {
                std::cerr << "Unknown exception in nanolog latency worker thread " << i << std::endl;
            }
        });
    }
    
    // Wait for all threads to be ready, then start
    while (ready_count.load() < params.num_threads) {
        std::this_thread::yield();
    }
    start_flag.store(true);
    
    // Wait for completion
    for (auto& t : threads) {
        t.join();
    }
    
    auto end_time = high_resolution_clock::now();
    result.duration_seconds = duration_cast<microseconds>(end_time - start_time).count() / 1000000.0;
    
    // Merge latency samples
    for (const auto& latencies : thread_latencies) {
        result.latency_samples.insert(result.latency_samples.end(), latencies.begin(), latencies.end());
    }
    
    calculate_latency_stats(result);
    result.operations_per_second = result.total_operations / result.duration_seconds;
    
    return result;
}

BenchmarkResults BenchmarkRunner::run_throughput_benchmark_nanolog(const BenchmarkParams& params) {
    BenchmarkResults result;
    result.logger_name = "NanoLog Logger";
    result.mode_name = "Throughput";
    result.num_threads = params.num_threads;
    result.total_operations = params.num_threads * params.operations_per_thread;
    
    // Ensure the global logger is initialized by getting it first
    auto* global_logger = kutrace::RPCNanoLogger::get();
    if (!global_logger || !global_logger->is_ready()) {
        std::cerr << "Failed to initialize global nanolog logger" << std::endl;
        return result;
    }
    
    // Thread synchronization
    std::vector<std::thread> threads;
    std::vector<std::vector<double>> thread_latencies(params.num_threads);
    
    std::atomic<int> ready_count{0};
    std::atomic<bool> start_flag{false};
    
    auto start_time = high_resolution_clock::now();
    
    // Launch threads
    for (int i = 0; i < params.num_threads; ++i) {
        threads.emplace_back([this, i, &params, &thread_latencies, &ready_count, &start_flag]() {
            try {
                ready_count.fetch_add(1);
                while (!start_flag.load()) {
                    std::this_thread::yield();
                }
                
                nanolog_worker(i, params, thread_latencies[i], false);
            } catch (const std::exception& e) {
                std::cerr << "Exception in nanolog throughput worker thread " << i << ": " << e.what() << std::endl;
            } catch (...) {
                std::cerr << "Unknown exception in nanolog throughput worker thread " << i << std::endl;
            }
        });
    }
    
    // Wait for all threads to be ready, then start
    while (ready_count.load() < params.num_threads) {
        std::this_thread::yield();
    }
    start_flag.store(true);
    
    // Wait for completion
    for (auto& t : threads) {
        t.join();
    }
    
    auto end_time = high_resolution_clock::now();
    result.duration_seconds = duration_cast<microseconds>(end_time - start_time).count() / 1000000.0;
    result.operations_per_second = result.total_operations / result.duration_seconds;
    
    return result;
}

void BenchmarkRunner::binary_logger_worker(int thread_id, const BenchmarkParams& params, 
                                          std::vector<double>& latencies, bool measure_latency) {
    try {
        // Thread-local data
        std::string test_data = generate_test_data(params.message_size);
        kutrace::NetworkAddress client("127.0.0.1", 8080 + thread_id);
        kutrace::NetworkAddress server("127.0.0.1", 9090);
        kutrace::RPCMessage message(test_data);
        
        // Get the global logger instance
        auto* logger = kutrace::RPCLogger::get();
        if (!logger) {
            std::cerr << "Failed to get binary logger instance in thread " << thread_id << std::endl;
            return;
        }
        
        if (measure_latency) {
            latencies.reserve(params.operations_per_thread);
        }
        
        // Warmup
        for (int i = 0; i < params.warmup_operations; ++i) {
            uint32_t rpcid = thread_id * 1000000 + i;
            logger->log_client_send(rpcid, 0, client, server, "test_method", message);
        }
        
        // Actual benchmark
        for (int i = 0; i < params.operations_per_thread; ++i) {
            auto start = high_resolution_clock::now();
            
            uint32_t rpcid = thread_id * 1000000 + params.warmup_operations + i;
            logger->log_client_send(rpcid, 0, client, server, "test_method", message);
            
            if (measure_latency) {
                auto end = high_resolution_clock::now();
                double latency_us = duration_cast<nanoseconds>(end - start).count() / 1000.0;
                latencies.push_back(latency_us);
            }
        }
    } catch (const std::exception& e) {
        std::cerr << "Exception in binary_logger_worker thread " << thread_id << ": " << e.what() << std::endl;
    } catch (...) {
        std::cerr << "Unknown exception in binary_logger_worker thread " << thread_id << std::endl;
    }
}

void BenchmarkRunner::nanolog_worker(int thread_id, const BenchmarkParams& params, 
                                    std::vector<double>& latencies, bool measure_latency) {
    try {
        // NanoLog requires preallocate() to be called in each thread
#ifdef KUTRACE_NANOLOG_ENABLE
        NanoLog::preallocate();
#endif
        
        // Thread-local data
        std::string test_data = generate_test_data(params.message_size);
        kutrace::NetworkAddress client("127.0.0.1", 8080 + thread_id);
        kutrace::NetworkAddress server("127.0.0.1", 9090);
        kutrace::RPCMessage message(test_data);
        
        // Get the global logger instance
        auto* logger = kutrace::RPCNanoLogger::get();
        if (!logger) {
            std::cerr << "Failed to get nanolog logger instance in thread " << thread_id << std::endl;
            return;
        }
        
        if (measure_latency) {
            latencies.reserve(params.operations_per_thread);
        }
        
        // Warmup
        for (int i = 0; i < params.warmup_operations; ++i) {
            uint32_t rpcid = thread_id * 1000000 + i;
            logger->log_client_send(rpcid, 0, client, server, "test_method", message);
        }
        
        // Actual benchmark
        for (int i = 0; i < params.operations_per_thread; ++i) {
            auto start = high_resolution_clock::now();
            
            uint32_t rpcid = thread_id * 1000000 + params.warmup_operations + i;
            logger->log_client_send(rpcid, 0, client, server, "test_method", message);
            
            if (measure_latency) {
                auto end = high_resolution_clock::now();
                double latency_us = duration_cast<nanoseconds>(end - start).count() / 1000.0;
                latencies.push_back(latency_us);
            }
        }
    } catch (const std::exception& e) {
        std::cerr << "Exception in nanolog_worker thread " << thread_id << ": " << e.what() << std::endl;
    } catch (...) {
        std::cerr << "Unknown exception in nanolog_worker thread " << thread_id << std::endl;
    }
}

void BenchmarkRunner::calculate_latency_stats(BenchmarkResults& results) {
    if (results.latency_samples.empty()) {
        return;
    }
    
    // Sort samples for percentile calculations
    std::sort(results.latency_samples.begin(), results.latency_samples.end());
    
    // Calculate statistics
    results.min_latency_us = results.latency_samples.front();
    results.max_latency_us = results.latency_samples.back();
    
    // Average
    double sum = 0.0;
    for (double latency : results.latency_samples) {
        sum += latency;
    }
    results.avg_latency_us = sum / results.latency_samples.size();
    
    // Percentiles
    size_t n = results.latency_samples.size();
    results.p50_latency_us = results.latency_samples[n * 0.5];
    results.p95_latency_us = results.latency_samples[n * 0.95];
    results.p99_latency_us = results.latency_samples[n * 0.99];
}

void BenchmarkRunner::save_results_to_file(const BenchmarkResults& results, const std::string& filename) {
    std::ofstream file(filename);
    if (!file.is_open()) {
        std::cerr << "Failed to open results file: " << filename << std::endl;
        return;
    }
    
    file << "Logger,Mode,Threads,TotalOps,Duration(s),OpsPerSec,AvgLatency(us),MinLatency(us),MaxLatency(us),P50(us),P95(us),P99(us)\n";
    file << results.logger_name << ","
         << results.mode_name << ","
         << results.num_threads << ","
         << results.total_operations << ","
         << std::fixed << std::setprecision(6) << results.duration_seconds << ","
         << std::fixed << std::setprecision(2) << results.operations_per_second << ","
         << std::fixed << std::setprecision(3) << results.avg_latency_us << ","
         << std::fixed << std::setprecision(3) << results.min_latency_us << ","
         << std::fixed << std::setprecision(3) << results.max_latency_us << ","
         << std::fixed << std::setprecision(3) << results.p50_latency_us << ","
         << std::fixed << std::setprecision(3) << results.p95_latency_us << ","
         << std::fixed << std::setprecision(3) << results.p99_latency_us << "\n";
    
    file.close();
}

void BenchmarkRunner::save_latency_samples(const BenchmarkResults& results, const std::string& filename) {
    if (results.latency_samples.empty()) {
        return;
    }
    
    std::ofstream file(filename);
    if (!file.is_open()) {
        std::cerr << "Failed to open latency samples file: " << filename << std::endl;
        return;
    }
    
    file << "Latency(us)\n";
    for (double latency : results.latency_samples) {
        file << std::fixed << std::setprecision(3) << latency << "\n";
    }
    
    file.close();
}

void BenchmarkRunner::print_results(const BenchmarkResults& results) {
    std::cout << "\n=== " << results.logger_name << " - " << results.mode_name << " Results ===\n";
    std::cout << "Threads:           " << results.num_threads << "\n";
    std::cout << "Total Operations:  " << results.total_operations << "\n";
    std::cout << "Duration:          " << std::fixed << std::setprecision(3) << results.duration_seconds << " seconds\n";
    std::cout << "Throughput:        " << std::fixed << std::setprecision(2) << results.operations_per_second << " ops/sec\n";
    
    if (!results.latency_samples.empty()) {
        std::cout << "Average Latency:   " << std::fixed << std::setprecision(3) << results.avg_latency_us << " μs\n";
        std::cout << "Min Latency:       " << std::fixed << std::setprecision(3) << results.min_latency_us << " μs\n";
        std::cout << "Max Latency:       " << std::fixed << std::setprecision(3) << results.max_latency_us << " μs\n";
        std::cout << "P50 Latency:       " << std::fixed << std::setprecision(3) << results.p50_latency_us << " μs\n";
        std::cout << "P95 Latency:       " << std::fixed << std::setprecision(3) << results.p95_latency_us << " μs\n";
        std::cout << "P99 Latency:       " << std::fixed << std::setprecision(3) << results.p99_latency_us << " μs\n";
    }
    std::cout << std::endl;
}

void BenchmarkRunner::generate_comparison_report() {
    if (results_.size() < 2) {
        std::cout << "Not enough results for comparison." << std::endl;
        return;
    }
    
    std::ofstream file(output_dir_ + "/comparison_report.txt");
    if (!file.is_open()) {
        std::cerr << "Failed to open comparison report file" << std::endl;
        return;
    }
    
    file << "KUTrace Logging Benchmark Comparison Report\n";
    file << "============================================\n\n";
    
    for (const auto& result : results_) {
        file << result.logger_name << " - " << result.mode_name << ":\n";
        file << "  Throughput: " << std::fixed << std::setprecision(2) << result.operations_per_second << " ops/sec\n";
        if (!result.latency_samples.empty()) {
            file << "  Avg Latency: " << std::fixed << std::setprecision(3) << result.avg_latency_us << " μs\n";
            file << "  P95 Latency: " << std::fixed << std::setprecision(3) << result.p95_latency_us << " μs\n";
        }
        file << "\n";
    }
    
    file.close();
    std::cout << "Comparison report saved to: " << output_dir_ + "/comparison_report.txt" << std::endl;
}

std::string BenchmarkRunner::generate_test_data(int size) {
    static std::random_device rd;
    static std::mt19937 gen(rd());
    static std::uniform_int_distribution<char> dis('a', 'z');
    
    std::string data;
    data.reserve(size);
    for (int i = 0; i < size; ++i) {
        data += dis(gen);
    }
    return data;
}

std::string BenchmarkRunner::get_timestamp_string() {
    auto now = std::chrono::system_clock::now();
    auto time_t = std::chrono::system_clock::to_time_t(now);
    auto ms = duration_cast<milliseconds>(now.time_since_epoch()) % 1000;
    
    std::stringstream ss;
    ss << std::put_time(std::localtime(&time_t), "%Y%m%d_%H%M%S");
    ss << "_" << std::setfill('0') << std::setw(3) << ms.count();
    return ss.str();
} 