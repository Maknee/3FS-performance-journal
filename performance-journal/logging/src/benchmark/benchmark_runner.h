#pragma once

#include <string>
#include <vector>
#include <chrono>
#include <memory>
#include <fstream>

// Forward declare the logger types
namespace kutrace {
    class RPCLogger;
    class RPCNanoLogger;
}

// Benchmark configuration enums
enum class LoggerType {
    Binary,
    NanoLog,
    Both
};

enum class BenchmarkMode {
    Latency,
    Throughput,
    Both
};

// Benchmark parameters structure
struct BenchmarkParams {
    int num_threads = 1;
    int operations_per_thread = 100000;
    int message_size = 64;
    int warmup_operations = 1000;
    int num_runs = 3;
    size_t batch_size = 10000;
    size_t timeout_ms = 10;
};

// Benchmark results structure
struct BenchmarkResults {
    std::string logger_name;
    std::string mode_name;
    int num_threads;
    int total_operations;
    double duration_seconds;
    double operations_per_second;
    double avg_latency_us;
    double min_latency_us;
    double max_latency_us;
    double p50_latency_us;
    double p95_latency_us;
    double p99_latency_us;
    std::vector<double> latency_samples;
    
    BenchmarkResults() : 
        num_threads(0), total_operations(0), duration_seconds(0.0),
        operations_per_second(0.0), avg_latency_us(0.0), min_latency_us(0.0),
        max_latency_us(0.0), p50_latency_us(0.0), p95_latency_us(0.0), p99_latency_us(0.0) {}
};

// Main benchmark runner class
class BenchmarkRunner {
public:
    BenchmarkRunner(const std::string& output_dir, bool verbose = false);
    ~BenchmarkRunner();
    
    // Run benchmarks for specific logger types
    bool run_binary_benchmark(const BenchmarkParams& params, BenchmarkMode mode);
    bool run_nanolog_benchmark(const BenchmarkParams& params, BenchmarkMode mode);
    
    // Generate comparison reports
    void generate_comparison_report();
    
    // Get accumulated results
    const std::vector<BenchmarkResults>& get_results() const { return results_; }

private:
    std::string output_dir_;
    bool verbose_;
    std::vector<BenchmarkResults> results_;
    
    // Internal benchmark functions
    BenchmarkResults run_latency_benchmark_binary(const BenchmarkParams& params);
    BenchmarkResults run_throughput_benchmark_binary(const BenchmarkParams& params);
    BenchmarkResults run_latency_benchmark_nanolog(const BenchmarkParams& params);
    BenchmarkResults run_throughput_benchmark_nanolog(const BenchmarkParams& params);
    
    // Utility functions
    void calculate_latency_stats(BenchmarkResults& results);
    void save_results_to_file(const BenchmarkResults& results, const std::string& filename);
    void save_latency_samples(const BenchmarkResults& results, const std::string& filename);
    void print_results(const BenchmarkResults& results);
    
    // Thread worker functions
    void binary_logger_worker(int thread_id, const BenchmarkParams& params, 
                            std::vector<double>& latencies, bool measure_latency);
    void nanolog_worker(int thread_id, const BenchmarkParams& params, 
                       std::vector<double>& latencies, bool measure_latency);
    
    // Helper functions
    std::string generate_test_data(int size);
    std::string get_timestamp_string();
}; 