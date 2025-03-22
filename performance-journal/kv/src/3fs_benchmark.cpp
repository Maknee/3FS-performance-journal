#include <iostream>
#include <fstream>
#include <string>
#include <vector>
#include <chrono>
#include <cstring>
#include <fcntl.h>
#include <unistd.h>
#include <sys/time.h>
#include <algorithm>
#include <filesystem>
#include <iomanip>
#include <numeric>
#include <cmath>
#include <thread>
#include <atomic>

// Optional io_uring support
#include <liburing.h>

// 3fs
#include <hf3fs_usrbio.h>

// Third-party libraries
#include <nlohmann/json.hpp>
#include <cxxopts.hpp>

#include <kutrace_lib.h>

#include <fmt/format.h>

#ifdef BLOCK_SIZE
#undef BLOCK_SIZE
#endif

#include <concurrentqueue.h>

// For convenience
namespace fs = std::filesystem;
using json = nlohmann::json;

// Configuration
constexpr const char* DEFAULT_MOUNT_POINT = "/hf3fs/mount/point";  // Default mount point
constexpr size_t DEFAULT_BLOCK_SIZE = (32 << 20);                   // 32MB per IO block
constexpr size_t DEFAULT_KV_CACHE_SIZE = 512;                       // Default size of each KV cache entry in bytes
constexpr size_t DEFAULT_IO_DEPTH = 0;                              // Default IO depth

// Mode enums
enum class BenchmarkMode {
    USRBIO,    // Use 3FS USRBIO API
    IO_URING,   // Use Linux io_uring API
    LIBC        // Standard libc read/write
};

enum class FileMode {
    READ,   // Open for reading
    WRITE   // Open for writing (creates and truncates by default)
};

int open_file_with_options(const std::string& filename, FileMode mode,
                          bool use_direct_io, int fadvise_mode, int thread_id = -1) {
    int open_flags = 0;

    // Set access mode and related flags
    if (mode == FileMode::WRITE) {
        open_flags |= O_WRONLY | O_CREAT | O_TRUNC;
    } else {
        open_flags |= O_RDONLY;
    }

    // Set direct I/O flag if needed
    if (use_direct_io) {
        open_flags |= O_DIRECT;
    }

    // Open the file
    int fd = open(filename.c_str(), open_flags, 0644);
    if (fd < 0) {
        // Construct appropriate error message based on context
        std::string operation = (mode == FileMode::WRITE) ? "write to" : "read from";

        if (thread_id >= 0) {
            std::cerr << "Thread " << thread_id << " failed to open file for " << operation
                      << " (" << filename << "): " << strerror(errno) << std::endl;
        } else {
            std::cerr << "Failed to open file for " << operation
                      << " (" << filename << "): " << strerror(errno) << std::endl;
        }
        return -1;
    }

    // Apply fadvise if we're NOT using direct I/O (i.e., using page cache)
    if (!use_direct_io) {
        posix_fadvise(fd, 0, 0, fadvise_mode);
    }

    return fd;
}

// Structure to track latency statistics
struct LatencyStats {
    std::vector<double> latencies_ms;  // Individual latencies in milliseconds
    std::atomic<std::size_t> latencies_index;
    // Pre-allocate space for latencies
    void reserve(size_t size) {
        latencies_ms.resize(size);
        latencies_index = 0;
    }

    // Add a latency measurement
    void add_latency(std::chrono::high_resolution_clock::time_point start,
                    std::chrono::high_resolution_clock::time_point end) {
        std::chrono::duration<double, std::milli> duration = end - start;
        auto i = latencies_index.fetch_add(1, std::memory_order_relaxed);
        if(i < latencies_ms.size())
          latencies_ms[i] = duration.count();
    }

    // Print latency statistics
    void print_stats(const std::string& operation_type) const {
        if (latencies_ms.empty()) {
            std::cout << "No latency data available for " << operation_type << std::endl;
            return;
        }

        // Calculate statistics
        std::vector<double> sorted_latencies = latencies_ms;
        std::sort(sorted_latencies.begin(), sorted_latencies.end());

        double min = sorted_latencies.front();
        double max = sorted_latencies.back();
        double median = sorted_latencies[sorted_latencies.size() / 2];
        double p95 = sorted_latencies[static_cast<size_t>(sorted_latencies.size() * 0.95)];
        double p99 = sorted_latencies[static_cast<size_t>(sorted_latencies.size() * 0.99)];
        double avg = std::accumulate(sorted_latencies.begin(), sorted_latencies.end(), 0.0) / sorted_latencies.size();

        // Calculate standard deviation
        double sum_squared_diff = 0.0;
        for (double latency : sorted_latencies) {
            double diff = latency - avg;
            sum_squared_diff += diff * diff;
        }
        double stddev = std::sqrt(sum_squared_diff / sorted_latencies.size());

        // Print statistics
        std::cout << "\n" << operation_type << " Latency Statistics (ms):" << std::endl;
        std::cout << std::fixed << std::setprecision(3);
        std::cout << "  Total operations: " << latencies_ms.size() << std::endl;
        std::cout << "  Min:    " << min << std::endl;
        std::cout << "  Max:    " << max << std::endl;
        std::cout << "  Avg:    " << avg << std::endl;
        std::cout << "  Median: " << median << std::endl;
        std::cout << "  StdDev: " << stddev << std::endl;
        std::cout << "  p95:    " << p95 << std::endl;
        std::cout << "  p99:    " << p99 << std::endl;
    }

    // Save detailed latency data to a CSV file
    void save_to_csv(const std::string& filename, const std::string& operation_type) const {
        if (latencies_ms.empty()) {
            std::cerr << "No latency data to save for " << operation_type << std::endl;
            return;
        }

        std::ofstream file(filename);
        if (!file.is_open()) {
            std::cerr << "Failed to open file for writing: " << filename << std::endl;
            return;
        }

        // Write header
        file << "operation,latency_ms\n";

        // Write data
        for (const auto& latency : latencies_ms) {
            file << operation_type << "," << std::fixed << std::setprecision(3) << latency << "\n";
        }

        std::cout << "Latency data saved to " << filename << std::endl;
    }
};

// Global configuration
struct Config {
    std::string mount_point = DEFAULT_MOUNT_POINT;
    std::string jsonl_file;
    std::string output_file;
    uint64_t kv_cache_size = DEFAULT_KV_CACHE_SIZE;
    uint64_t block_size = DEFAULT_BLOCK_SIZE;
    int io_depth = DEFAULT_IO_DEPTH;
    bool skip_write = false;
    bool skip_read = false;
    bool verbose = false;
    bool save_latency_data = false;
    std::string latency_output_dir = "./";
    BenchmarkMode mode = BenchmarkMode::USRBIO;
    bool io_uring_available = false;
    uint32_t num_threads = 1;
    bool use_direct_io = true;     // Use O_DIRECT flag (bypass page cache)
    int fadvise_mode = POSIX_FADV_NORMAL; // Default fadvise mode
    bool kutrace = false;
    int kutrace_control = DO_IPC | DO_WRAP;
    std::string program_name;
};

void start_kutrace(const Config& config) {
    if (config.kutrace) {
        kutrace::DoReset(config.kutrace_control);
        kutrace::DoInit(config.program_name.c_str());
        kutrace::DoOn();
    }
}

void stop_kutrace(const Config& config) {
    if (config.kutrace) {
        char namebuf[256];
        kutrace::stop(kutrace::MakeTraceFileName(config.program_name.c_str(), namebuf));
    }
}

// Function to check if io_uring is available
bool check_io_uring_available() {
    struct io_uring ring;
    int ret = io_uring_queue_init(8, &ring, 0);
    if (ret < 0) {
        return false;
    }
    io_uring_queue_exit(&ring);
    return true;
}

// Function to create test data for benchmarking
void create_test_data(uint8_t* buffer, size_t size) {
    for (size_t i = 0; i < size; i++) {
        buffer[i] = 'A' + (i % 26);
    }
}

// Function to parse JSONL and find max hash ID using nlohmann/json
uint64_t find_max_hash_id(const std::string& jsonl_file) {
    std::ifstream file(jsonl_file);
    if (!file.is_open()) {
        std::cerr << "Failed to open JSONL file: " << jsonl_file << std::endl;
        return 0;
    }

    std::string line;
    uint64_t max_hash_id = 0;

    while (std::getline(file, line)) {
        try {
            auto j = json::parse(line);
            if (j.contains("hash_ids") && j["hash_ids"].is_array()) {
                for (const auto& hash_id : j["hash_ids"]) {
                    if (hash_id.is_number()) {
                        max_hash_id = std::max(max_hash_id, hash_id.get<uint64_t>());
                    }
                }
            }
        } catch (const json::parse_error&) {
            continue;
        }
    }

    return max_hash_id;
}

// Structure to hold a line's hash IDs and metadata
struct LineHashIds {
    std::vector<uint64_t> hash_ids;
    uint64_t timestamp;
    uint64_t input_length;
    uint64_t output_length;
    std::string line_text;  // Store original line for reference
};

// Function to load hash IDs from JSONL file, line by line
std::vector<LineHashIds> load_jsonl_lines(const std::string& jsonl_file) {
    std::ifstream file(jsonl_file);
    if (!file.is_open()) {
        std::cerr << "Failed to open JSONL file: " << jsonl_file << std::endl;
        return {};
    }

    std::vector<LineHashIds> lines_data;
    std::string line;

    while (std::getline(file, line)) {
        try {
            auto j = json::parse(line);
            if (j.contains("hash_ids") && j["hash_ids"].is_array()) {
                LineHashIds line_data;
                line_data.line_text = line;

                // Extract metadata
                if (j.contains("timestamp")) {
                    line_data.timestamp = j["timestamp"].get<uint64_t>();
                }
                if (j.contains("input_length")) {
                    line_data.input_length = j["input_length"].get<uint64_t>();
                }
                if (j.contains("output_length")) {
                    line_data.output_length = j["output_length"].get<uint64_t>();
                }

                // Extract hash_ids
                for (const auto& hash_id : j["hash_ids"]) {
                    if (hash_id.is_number()) {
                        line_data.hash_ids.push_back(hash_id.get<uint64_t>());
                    }
                }

                if (!line_data.hash_ids.empty()) {
                    lines_data.push_back(line_data);
                }
            }
        } catch (const json::parse_error&) {
            std::cerr << "Error parsing line: " << line << std::endl;
            continue;
        }
    }

    return lines_data;
}

// Simplified benchmark write performance function using USRBIO with latency tracking
void benchmark_write_3fs(const Config& config, uint64_t num_blocks) {
    std::cout << "Starting USRBIO write benchmark with " << num_blocks << " blocks ("
              << config.block_size << " bytes each)..." << std::endl;

    // Create and initialize USRBIO structures
    struct hf3fs_ior ior;
    int ret_create = hf3fs_iorcreate4(&ior, config.mount_point.c_str(), num_blocks,
                                     false, config.io_depth, 0, -1, 0);
    if (ret_create != 0) {
        std::cerr << "Failed to create ior: " << strerror(-ret_create) << std::endl;
        return;
    }

    struct hf3fs_iov iov;
    int ret_iov = hf3fs_iovcreate(&iov, config.mount_point.c_str(),
                                 num_blocks * config.block_size, 0, -1);
    if (ret_iov != 0) {
        std::cerr << "Failed to create iov: " << strerror(-ret_iov) << std::endl;
        hf3fs_iordestroy(&ior);
        return;
    }

    // Create and register file descriptor
    int fd = open_file_with_options(
        config.output_file,
        FileMode::WRITE,
        config.use_direct_io,
        config.fadvise_mode
    );
    if (fd < 0) {
        std::cerr << "Failed to open output file: " << strerror(errno) << std::endl;
        hf3fs_iovdestroy(&iov);
        hf3fs_iordestroy(&ior);
        return;
    }

    hf3fs_reg_fd(fd, 0);

    // Fill IOV buffer with test data
    uint8_t* buffer_ptr = static_cast<uint8_t*>(iov.base);
    for (uint64_t i = 0; i < num_blocks; i++) {
        create_test_data(buffer_ptr + (i * config.block_size), config.block_size);
    }

    // Create latency tracking structure and preallocate space
    LatencyStats latency_stats;
    latency_stats.reserve(num_blocks);

    // Record start time for overall throughput measurement
    auto start_time_overall = std::chrono::high_resolution_clock::now();

    // Submit IO requests with individual timing
    std::vector<std::chrono::high_resolution_clock::time_point> start_times(num_blocks);

    start_kutrace(config);

    auto kutrace_index = 1;
    if (config.kutrace) {
        kutrace::addname(KUTRACE_METHODNAME, kutrace_index, "3FSWrite");
        kutrace::addevent(KUTRACE_RPCIDREQ, kutrace_index);
        kutrace::mark_a("write");
    }

    // Prepare all IO requests first
    for (uint64_t i = 0; i < num_blocks; i++) {
        start_times[i] = std::chrono::high_resolution_clock::now();

        if (config.kutrace) { kutrace::mark_b("prep"); }
        if (config.kutrace) { kutrace::mark_d(i); }

        int ret = hf3fs_prep_io(&ior, &iov, false,
                               buffer_ptr + (i * config.block_size),
                               fd, i * config.block_size, config.block_size,
                               reinterpret_cast<void*>(i));
        if (ret < 0) {
            std::cerr << "Failed to prepare IO request " << i << ": " << ret << std::endl;
            hf3fs_dereg_fd(fd);
            close(fd);
            hf3fs_iovdestroy(&iov);
            hf3fs_iordestroy(&ior);
            return;
        }
    }

    if (config.kutrace) { kutrace::mark_a("submit"); }

    // Submit all IO requests at once
    hf3fs_submit_ios(&ior);

    if (config.kutrace) { kutrace::mark_b("wait"); }

    // Wait for IO completion
    std::vector<struct hf3fs_cqe> cqes(num_blocks);
    int completed = hf3fs_wait_for_ios(&ior, cqes.data(), num_blocks, num_blocks, nullptr);

    if (config.kutrace) {
        kutrace::addname(KUTRACE_METHODNAME, kutrace_index, "3FSWait");
        kutrace::mark_c("/write");
    }

    // End timing for overall throughput
    auto end_time_overall = std::chrono::high_resolution_clock::now();
    std::chrono::duration<double> elapsed = end_time_overall - start_time_overall;

    // Process completion events and record latencies
    int error_count = 0;
    for (int i = 0; i < completed; i++) {
        uint64_t block_idx = reinterpret_cast<uintptr_t>(cqes[i].userdata);
        auto end_time = std::chrono::high_resolution_clock::now();

        if (cqes[i].result >= 0) {
            latency_stats.add_latency(start_times[block_idx], end_time);
        } else {
            error_count++;
            if (config.verbose || error_count <= 5) {
                std::cerr << "IO operation " << block_idx
                         << " failed with error " << cqes[i].result << " ("
                         << strerror(-cqes[i].result) << ")" << std::endl;
            }
        }
    }

    if (config.kutrace) { kutrace::addevent(KUTRACE_RPCIDREQ, 0); }

    if (error_count > 5 && !config.verbose) {
        std::cerr << "... and " << (error_count - 5) << " more errors" << std::endl;
    }

    // Report overall results
    std::cout << "Write completed: " << completed << "/" << num_blocks << " operations" << std::endl;
    std::cout << "Total time: " << elapsed.count() << " seconds" << std::endl;
    std::cout << "Throughput: " << (num_blocks * config.block_size) / (1024.0 * 1024.0) / elapsed.count()
              << " MB/s" << std::endl;

    // Print latency statistics
    latency_stats.print_stats("Write");

    // Save detailed latency data if requested
    if (config.save_latency_data || config.verbose) {
        std::string latency_file = config.latency_output_dir + "/" +
                                  fs::path(config.output_file).filename().string() +
                                  ".write_latency.csv";
        latency_stats.save_to_csv(latency_file, "write");
    }

    // Cleanup
    hf3fs_dereg_fd(fd);
    close(fd);
    hf3fs_iovdestroy(&iov);
    hf3fs_iordestroy(&ior);
}

struct ReadTask {
    size_t line_idx;
};

// Optimized benchmark read function with memory reuse
// Benchmark function using ConcurrentQueue
void benchmark_read_3fs(const Config& config) {
    std::cout << "Starting concurrent queue-based read benchmark with "
              << config.num_threads << " threads..." << std::endl;

    // Load lines with hash_ids from JSONL file
    std::vector<LineHashIds> lines_data = load_jsonl_lines(config.jsonl_file);
    if (lines_data.empty()) {
        std::cerr << "No valid lines with hash_ids found in " << config.jsonl_file << std::endl;
        return;
    }

    // Gather statistics about the data
    size_t total_hash_ids = 0;
    size_t max_line_hash_count = 0;
    for (const auto& line : lines_data) {
        total_hash_ids += line.hash_ids.size();
        max_line_hash_count = std::max(max_line_hash_count, line.hash_ids.size());
    }

    std::cout << "Processing " << lines_data.size() << " lines with a total of "
              << total_hash_ids << " hash_ids entries" << std::endl;

    // Create the concurrent queue for tasks
    moodycamel::ConcurrentQueue<ReadTask> task_queue(lines_data.size());

    // Pre-fill the queue with all tasks
    for (size_t i = 0; i < lines_data.size(); i++) {
        ReadTask task = { i };
        task_queue.enqueue(task);
    }

    // Atomic counters for tracking progress
    std::atomic<size_t> completed_lines = 0;
    std::atomic<size_t> completed_ops = 0;
    std::atomic<size_t> error_count = 0;
    std::atomic<size_t> total_reads_submitted = 0;

    // Shared latency stats collectors
    LatencyStats op_latency_stats;
    LatencyStats line_latency_stats;
    op_latency_stats.reserve(total_hash_ids);
    line_latency_stats.reserve(lines_data.size());

    // Record start time for overall throughput
    auto start_time_overall = std::chrono::high_resolution_clock::now();

    // Create and start worker threads
    std::vector<std::thread> threads;

    start_kutrace(config);

    for (uint32_t thread_id = 0; thread_id < config.num_threads; thread_id++) {
        threads.emplace_back([&, thread_id]() {
            // Open and register file descriptor (shared across threads)
            int fd = open_file_with_options(
                config.output_file,
                FileMode::READ,
                config.use_direct_io,
                config.fadvise_mode,
                thread_id
            );
            if (fd < 0) {
                std::cerr << "Failed to open input file: " << strerror(errno) << std::endl;
                return;
            }
            hf3fs_reg_fd(fd, 0);

            // Per-thread USRBIO structures
            struct hf3fs_ior ior;
            struct hf3fs_iov iov;

            int numa = -1;

            // Initialize thread-local USRBIO structures
            int ret_create = hf3fs_iorcreate4(&ior, config.mount_point.c_str(),
                                             max_line_hash_count, true,
                                             config.io_depth, 0, numa, 0);

            int ret_iov = hf3fs_iovcreate(&iov, config.mount_point.c_str(),
                                         max_line_hash_count * config.kv_cache_size, 0, numa);

            if (ret_create != 0 || ret_iov != 0) {
                std::cerr << "Thread " << thread_id
                         << " failed to initialize USRBIO structures" << std::endl;
                return;
            }

            // Thread-local buffer
            uint8_t* buffer_ptr = static_cast<uint8_t*>(iov.base);

            if (!buffer_ptr) {
                std::cerr << "Thread " << thread_id << " failed to allocate buffer" << std::endl;
                hf3fs_iovdestroy(&iov);
                hf3fs_iordestroy(&ior);
                return;
            }

            // Prepare completion events array
            std::vector<struct hf3fs_cqe> cqes(max_line_hash_count);

            // Track start times for individual operations
            std::vector<std::chrono::high_resolution_clock::time_point> start_times(max_line_hash_count);

            // Process tasks from the queue
            ReadTask task;
            while (task_queue.try_dequeue(task)) {
                const auto& line = lines_data[task.line_idx];
                size_t line_hash_count = line.hash_ids.size();

                if (line_hash_count == 0) {
                    completed_lines++;
                    continue;
                }

                // Record start time for this line
                auto start_time_line = std::chrono::high_resolution_clock::now();

                if (config.kutrace) {
                    kutrace::addname(KUTRACE_METHODNAME, task.line_idx, "3FSRead");
                    kutrace::addevent(KUTRACE_RPCIDREQ, task.line_idx);
                    kutrace::mark_a("read");
                    kutrace::mark_d(task.line_idx);
                }

                // Prepare read requests for all hash_ids in this line
                bool prep_failed = false;
                for (size_t i = 0; i < line_hash_count; i++) {
                    off_t offset = line.hash_ids[i] * config.kv_cache_size;
                    start_times[i] = std::chrono::high_resolution_clock::now();

                    if (config.kutrace) { kutrace::mark_b("prep"); }

                    int ret = hf3fs_prep_io(&ior, &iov, true,
                                          buffer_ptr + (i * config.kv_cache_size),
                                          fd, offset, config.kv_cache_size,
                                          reinterpret_cast<void*>(i));
                    if (ret < 0) {
                        std::cerr << "Failed to prepare IO request " << i << " for hash_id "
                                 << line.hash_ids[i] << " in line " << task.line_idx << ": "
                                 << ret << std::endl;

                        prep_failed = true;
                        break;
                    }
                }

                if (prep_failed) {
                    completed_lines++;
                    continue;
                }

                if (config.kutrace) { kutrace::mark_a("submit"); }

                // Submit all IO requests for this line at once
                hf3fs_submit_ios(&ior);

                if (config.kutrace) { kutrace::mark_b("wait"); }

                // Wait for IO completion
                int completed = hf3fs_wait_for_ios(&ior, cqes.data(), line_hash_count,
                                                 line_hash_count, nullptr);

                if (config.kutrace) {
                    kutrace::addname(KUTRACE_METHODNAME, task.line_idx, "WaitCqe");
                    kutrace::mark_c("/read");
                }

                // End timing for this line
                auto end_time_line = std::chrono::high_resolution_clock::now();
                line_latency_stats.add_latency(start_time_line, end_time_line);

                // Process completion events and record latencies
                int line_error_count = 0;
                for (int i = 0; i < completed; i++) {
                    size_t request_idx = reinterpret_cast<uintptr_t>(cqes[i].userdata);
                    auto end_time = std::chrono::high_resolution_clock::now();

                    if (cqes[i].result >= 0) {
                        op_latency_stats.add_latency(start_times[request_idx], end_time);
                        completed_ops++;
                    } else {
                        line_error_count++;
                        error_count++;
                    }

                }

                if (config.kutrace) { kutrace::addevent(KUTRACE_RPCIDREQ, 0); }

                // Update counters
                completed_lines++;

                // Optionally report progress
                if (config.verbose && completed_lines % 100 == 0) {
                    std::cout << "Thread " << thread_id << " completed "
                             << completed_lines << " lines" << std::endl;
                }
            }

            // Clean up thread resources
            hf3fs_iovdestroy(&iov);
            hf3fs_iordestroy(&ior);

            // Cleanup shared resources
            hf3fs_dereg_fd(fd);
            close(fd);
        });
    }

    // Wait for all threads to complete
    for (auto& thread : threads) {
        thread.join();
    }

    // End timing for overall throughput
    auto end_time_overall = std::chrono::high_resolution_clock::now();
    std::chrono::duration<double> elapsed = end_time_overall - start_time_overall;

    // Report overall results
    std::cout << "Read completed: " << completed_ops << "/" << total_hash_ids
              << " operations across " << completed_lines << "/" << lines_data.size()
              << " lines" << std::endl;
    std::cout << "Total time: " << elapsed.count() << " seconds" << std::endl;
    std::cout << "Throughput: " << (completed_ops * config.kv_cache_size) / (1024.0 * 1024.0) / elapsed.count()
              << " MB/s" << std::endl;

    if (error_count > 0) {
        std::cout << "Total errors: " << error_count << std::endl;
    }

    // Print latency statistics
    op_latency_stats.print_stats("Individual Read Operations");
    line_latency_stats.print_stats("Line Processing");
}

// Simplified benchmark write function using io_uring with latency tracking
void benchmark_write_io_uring(const Config& config, uint64_t num_blocks) {
    std::cout << "Starting io_uring write benchmark with " << num_blocks << " blocks ("
              << config.block_size << " bytes each)..." << std::endl;

    // Allocate memory for IO buffers
    std::vector<uint8_t> buffer(num_blocks * config.block_size);

    // Fill buffer with test data
    for (uint64_t i = 0; i < num_blocks; i++) {
        create_test_data(buffer.data() + (i * config.block_size), config.block_size);
    }

    // Open output file
    int fd = open_file_with_options(
        config.output_file,
        FileMode::WRITE,
        config.use_direct_io,
        config.fadvise_mode
    );
    if (fd < 0) {
        std::cerr << "Failed to open output file: " << strerror(errno) << std::endl;
        return;
    }

    // Initialize io_uring
    struct io_uring ring;
    int ret = io_uring_queue_init(config.io_depth > 0 ? config.io_depth : 32, &ring, 0);
    if (ret < 0) {
        std::cerr << "Failed to initialize io_uring: " << strerror(-ret) << std::endl;
        close(fd);
        return;
    }

    // Create latency tracking structure and preallocate space
    LatencyStats latency_stats;
    latency_stats.reserve(num_blocks);

    // Store start times for each operation
    std::vector<std::chrono::high_resolution_clock::time_point> start_times(num_blocks);

    auto start_time_overall = std::chrono::high_resolution_clock::now();

    // Prepare and submit IO requests
    struct io_uring_sqe *sqe;
    struct io_uring_cqe *cqe;
    uint64_t completed = 0;
    uint64_t submitted = 0;
    int error_count = 0;

    start_kutrace(config);

    while (completed < num_blocks) {
        if (config.kutrace) {
            kutrace::addname(KUTRACE_METHODNAME, submitted, "IouringPrepWrite");
            kutrace::addevent(KUTRACE_RPCIDREQ, submitted);
            kutrace::mark_a("write");
            kutrace::mark_d(submitted);
        }

        // Submit as many requests as possible
        while (submitted < num_blocks) {
            sqe = io_uring_get_sqe(&ring);
            if (!sqe) {
                // Queue is full, break and wait for completions
                break;
            }

            if (config.kutrace) { kutrace::mark_b("prep"); }

            // Record start time for this operation
            start_times[submitted] = std::chrono::high_resolution_clock::now();

            // Prepare write request
            io_uring_prep_write(sqe, fd, buffer.data() + (submitted * config.block_size),
                               config.block_size, submitted * config.block_size);
            // Store the block index for tracking
            sqe->user_data = submitted;

            submitted++;
        }

        if (config.kutrace) { kutrace::mark_a("submit"); }

        // Submit the batch
        ret = io_uring_submit(&ring);
        if (ret < 0) {
            std::cerr << "io_uring_submit failed: " << strerror(-ret) << std::endl;
            break;
        }

        if (config.kutrace) { kutrace::mark_b("wait"); }

        // Wait for at least one completion
        ret = io_uring_wait_cqe(&ring, &cqe);
        if (ret < 0) {
                      std::cerr << "io_uring_wait_cqe failed: " << strerror(-ret) << std::endl;
            break;
        }

        uint64_t iter_completed = 0;
        while (iter_completed < submitted - completed) {
            // Try to get as many completions as possible
            struct io_uring_cqe *cqes[submitted - completed];  // Process in batches of submitted - completed
            int count = io_uring_peek_batch_cqe(&ring, cqes, submitted - completed);

            if (count == 0) {
                // No completions yet, wait for at least one
                struct io_uring_cqe *cqe;
                int ret = io_uring_wait_cqe(&ring, &cqe);
                if (ret < 0) {
                    std::cerr << "io_uring_wait_cqe failed: " << strerror(-ret) << std::endl;
                    break;
                }

                // Process this single completion
                auto end_time = std::chrono::high_resolution_clock::now();
                uint64_t block_idx = cqe->user_data;

                if (config.kutrace) {
                    kutrace::addname(KUTRACE_METHODNAME, submitted, "IouringWaitCqe");
                    kutrace::mark_c("/writew");
                }

                if (cqe->res < 0) {
                    error_count++;
                    if (config.verbose || error_count <= 5) {
                        std::cerr << "IO operation " << block_idx
                                << " failed with error " << cqe->res
                                << " (" << strerror(-cqe->res) << ")" << std::endl;
                    }
                } else {
                    // Only record latency for successful operations
                    latency_stats.add_latency(start_times[block_idx], end_time);
                }

                io_uring_cqe_seen(&ring, cqe);
                iter_completed++;
                continue;
            }

            // Process the batch of completions
            for (int i = 0; i < count; i++) {
                auto end_time = std::chrono::high_resolution_clock::now();
                uint64_t block_idx = cqes[i]->user_data;
                if (config.kutrace) {
                    kutrace::addname(KUTRACE_METHODNAME, submitted, "IouringPeekCqe");
                    kutrace::mark_c("/write");
                }

                if (cqes[i]->res < 0) {
                    error_count++;
                    if (config.verbose || error_count <= 5) {
                        std::cerr << "IO operation " << block_idx
                                << " failed with error " << cqes[i]->res
                                << " (" << strerror(-cqes[i]->res) << ")" << std::endl;
                    }
                } else {
                    // Only record latency for successful operations
                    latency_stats.add_latency(start_times[block_idx], end_time);
                }

                io_uring_cqe_seen(&ring, cqes[i]);
                iter_completed++;
            }

            // Provide progress update if verbose
            if (config.verbose && completed % 100 == 0) {
                std::cout << "Completed " << completed << "/" << submitted << " operations" << std::endl;
            }
        }

        if (config.kutrace) { kutrace::addevent(KUTRACE_RPCIDREQ, 0); }

        completed += iter_completed;
    }

    // End timing for overall throughput
    auto end_time_overall = std::chrono::high_resolution_clock::now();
    std::chrono::duration<double> elapsed = end_time_overall - start_time_overall;

    // Report results
    std::cout << "Write completed: " << completed << "/" << num_blocks << " operations" << std::endl;
    std::cout << "Total time: " << elapsed.count() << " seconds" << std::endl;
    std::cout << "Throughput: " << (num_blocks * config.block_size) / (1024.0 * 1024.0) / elapsed.count()
              << " MB/s" << std::endl;

    if (error_count > 5 && !config.verbose) {
        std::cerr << "... and " << (error_count - 5) << " more errors" << std::endl;
    }

    // Print latency statistics
    latency_stats.print_stats("Write (io_uring)");

    // Save detailed latency data if requested
    if (config.save_latency_data || config.verbose) {
        std::string latency_file = config.latency_output_dir + "/" +
                                  fs::path(config.output_file).filename().string() +
                                  ".write_iouring_latency.csv";
        latency_stats.save_to_csv(latency_file, "write_iouring");
    }

    // Cleanup
    io_uring_queue_exit(&ring);
    close(fd);
}

// Removed timeout handling and added memory-ordered relaxed for atomics
void benchmark_read_io_uring(const Config& config) {
    std::cout << "Starting multithreaded io_uring read benchmark with "
              << config.num_threads << " threads..." << std::endl;

    // Load lines with hash_ids from JSONL file
    std::vector<LineHashIds> lines_data = load_jsonl_lines(config.jsonl_file);
    if (lines_data.empty()) {
        std::cerr << "No valid lines with hash_ids found in " << config.jsonl_file << std::endl;
        return;
    }

    // Count total hash_ids for reporting and find maximum line size
    size_t total_hash_ids = 0;
    size_t max_line_hash_count = 0;
    for (const auto& line : lines_data) {
        total_hash_ids += line.hash_ids.size();
        max_line_hash_count = std::max(max_line_hash_count, line.hash_ids.size());
    }

    std::cout << "Processing " << lines_data.size() << " lines with a total of "
              << total_hash_ids << " hash_ids entries" << std::endl;
    std::cout << "Maximum hash_ids per line: " << max_line_hash_count << std::endl;

    // Create the concurrent queue for tasks
    moodycamel::ConcurrentQueue<ReadTask> task_queue(lines_data.size());

    // Pre-fill the queue with all tasks
    for (size_t i = 0; i < lines_data.size(); i++) {
        ReadTask task = { i };
        task_queue.enqueue(task);
    }

    // Atomic counters for tracking progress
    std::atomic<size_t> completed_lines(0);
    std::atomic<size_t> completed_ops(0);
    std::atomic<size_t> error_count(0);
    std::atomic<size_t> total_reads_submitted(0);

    // Shared latency stats collectors
    LatencyStats op_latency_stats;
    LatencyStats line_latency_stats;
    op_latency_stats.reserve(total_hash_ids);
    line_latency_stats.reserve(lines_data.size());

    // Record start time for overall throughput measurement
    auto start_time_overall = std::chrono::high_resolution_clock::now();

    // Create and start worker threads
    std::vector<std::thread> threads;

    start_kutrace(config);

    for (uint32_t thread_id = 0; thread_id < config.num_threads; thread_id++) {
        threads.emplace_back([&, thread_id]() {
            // Open input file (each thread has its own file descriptor)
            int fd = open_file_with_options(
                config.output_file,
                FileMode::READ,
                config.use_direct_io,
                config.fadvise_mode,
                thread_id
            );
            if (fd < 0) {
                std::cerr << "Thread " << thread_id << " failed to open input file: "
                         << strerror(errno) << std::endl;
                return;
            }

            // Pre-allocate memory buffer for IO (reused across all lines)
            // Use posix_memalign for O_DIRECT compatibility
            uint8_t* buffer;
            if (posix_memalign((void**)&buffer, 512, max_line_hash_count * config.kv_cache_size) != 0) {
                std::cerr << "Thread " << thread_id << " failed to allocate aligned buffer memory" << std::endl;
                close(fd);
                return;
            }


            // Initialize io_uring once for all operations in this thread
            struct io_uring ring;
            int depth = config.io_depth > 0 ? config.io_depth : std::min(static_cast<int>(max_line_hash_count), 128);
            int ret = io_uring_queue_init(depth, &ring, 0);
            if (ret < 0) {
                std::cerr << "Thread " << thread_id << " failed to initialize io_uring: "
                         << strerror(-ret) << std::endl;
                free(buffer);
                close(fd);
                return;
            }

            // Pre-allocate arrays for tracking
            std::vector<std::chrono::high_resolution_clock::time_point> start_times(max_line_hash_count);

            // Process tasks from the queue
            ReadTask task;
            while (task_queue.try_dequeue(task)) {
                const auto& line = lines_data[task.line_idx];
                size_t line_hash_count = line.hash_ids.size();

                // Skip if line has no hash_ids
                if (line_hash_count == 0) {
                    completed_lines.fetch_add(1, std::memory_order_relaxed);
                    continue;
                }

                // Record start time for this line
                auto start_time_line = std::chrono::high_resolution_clock::now();

                // Track for this line's operations
                uint64_t submitted = 0;
                int line_error_count = 0;

                // Clear any pending completions to avoid stale data
                io_uring_cq_advance(&ring, io_uring_cq_ready(&ring));

                if (config.kutrace) {
                    kutrace::addname(KUTRACE_METHODNAME, task.line_idx, "IouringRead");
                    kutrace::addevent(KUTRACE_RPCIDREQ, task.line_idx);
                    kutrace::mark_a("read");
                    kutrace::mark_d(task.line_idx);
                }

                // Submit all operations for this line at once
                for (uint64_t i = 0; i < line_hash_count; i++) {
                    struct io_uring_sqe *sqe = io_uring_get_sqe(&ring);
                    if (!sqe) {
                        // If we run out of submission queue entries, submit what we have and try again
                        int submit_ret = io_uring_submit(&ring);
                        if (submit_ret < 0) {
                            std::cerr << "Thread " << thread_id << " io_uring_submit failed for line "
                                     << task.line_idx << ": " << strerror(-submit_ret) << std::endl;
                            break;
                        }

                        // Try again
                        sqe = io_uring_get_sqe(&ring);
                        if (!sqe) {
                            std::cerr << "Thread " << thread_id << " still failed to get SQE, giving up for this line" << std::endl;
                            break;
                        }
                    }

                    // Calculate file offset based on hash_id for this line
                    off_t offset = line.hash_ids[i] * config.kv_cache_size;

                    // Record start time for this operation
                    start_times[i] = std::chrono::high_resolution_clock::now();

                    if (config.kutrace) { kutrace::mark_b("prep"); }

                    // Prepare read request for this specific hash_id
                    io_uring_prep_read(sqe, fd, buffer + (i * config.kv_cache_size),
                                      config.kv_cache_size, offset);

                    // Store the request index for tracking
                    sqe->user_data = i;

                    submitted++;
                }

                // Final submission of any pending operations
                if (submitted > 0) {
                    if (config.kutrace) { kutrace::mark_a("submit"); }

                    int submit_ret = io_uring_submit(&ring);
                    if (submit_ret < 0) {
                        std::cerr << "Thread " << thread_id << " io_uring_submit failed for line "
                                 << task.line_idx << ": " << strerror(-submit_ret) << std::endl;
                        completed_lines.fetch_add(1, std::memory_order_relaxed);
                        continue; // Skip this line and try the next one
                    }
                } else {
                    // No submissions, skip this line
                    completed_lines.fetch_add(1, std::memory_order_relaxed);
                    continue;
                }

                // Process all completions for this line
                uint64_t line_completed = 0;

                // Wait for ALL submitted operations to complete
                while (line_completed < submitted) {
                    struct io_uring_cqe *cqe;

                    if (config.kutrace) { kutrace::mark_b("wait"); }

                    // Wait for at least one completion (no timeout)
                    int ret = io_uring_wait_cqe(&ring, &cqe);

                    if (ret < 0) {
                        std::cerr << "Thread " << thread_id << " io_uring_wait_cqe failed for line "
                                 << task.line_idx << ": " << strerror(-ret) << std::endl;
                        break;
                    }

                    // Process as many completions as possible in a batch
                    struct io_uring_cqe *cqes[submitted];
                    int count = io_uring_peek_batch_cqe(&ring, cqes, submitted);

                    if (count == 0) {
                        // No batch completions found, but we still have the single completion
                        // from io_uring_wait_cqe, so process it
                        auto end_time = std::chrono::high_resolution_clock::now();
                        uint64_t request_idx = cqe->user_data;

                        if (cqe->res < 0) {
                            line_error_count++;
                            error_count.fetch_add(1, std::memory_order_relaxed);
                            if (config.verbose || line_error_count <= 5) {
                                std::cerr << "Thread " << thread_id << " IO operation at index " << request_idx
                                         << " in line " << task.line_idx
                                         << " failed with error " << cqe->res
                                         << " (" << strerror(-cqe->res) << ")" << std::endl;
                            }
                        } else {
                            // Record latency for successful operations
                            op_latency_stats.add_latency(start_times[request_idx], end_time);
                            completed_ops.fetch_add(1, std::memory_order_relaxed);
                        }

                        if (config.kutrace) {
                            kutrace::addname(KUTRACE_METHODNAME, task.line_idx, "IouringWaitCqe");
                            kutrace::mark_c("/readw");
                        }

                        // Mark as seen
                        io_uring_cqe_seen(&ring, cqe);
                        line_completed++;
                    } else {
                        // Process all completions in the batch
                        for (int i = 0; i < count; i++) {
                            auto end_time = std::chrono::high_resolution_clock::now();
                            uint64_t request_idx = cqes[i]->user_data;

                            if (cqes[i]->res < 0) {
                                line_error_count++;
                                error_count.fetch_add(1, std::memory_order_relaxed);
                                if (config.verbose || line_error_count <= 5) {
                                    std::cerr << "Thread " << thread_id << " IO operation at index " << request_idx
                                             << " in line " << task.line_idx
                                             << " failed with error " << cqes[i]->res
                                             << " (" << strerror(-cqes[i]->res) << ")" << std::endl;
                                }
                            } else {
                                // Record latency for successful operations
                                op_latency_stats.add_latency(start_times[request_idx], end_time);
                                completed_ops.fetch_add(1, std::memory_order_relaxed);
                            }
                            if (config.kutrace) {
                                kutrace::addname(KUTRACE_METHODNAME, task.line_idx, "IouringPeekCqe");
                                kutrace::mark_c("/read");
                            }

                            // Mark as seen
                            io_uring_cqe_seen(&ring, cqes[i]);
                            line_completed++;
                        }
                    }
                }

                if (config.kutrace) { kutrace::addevent(KUTRACE_RPCIDREQ, 0); }

                // Report completion status
                if (line_completed < submitted) {
                    std::cerr << "Thread " << thread_id << " only completed " << line_completed
                             << "/" << submitted << " operations for line " << task.line_idx << std::endl;
                }

                // End timing for this line
                auto end_time_line = std::chrono::high_resolution_clock::now();
                line_latency_stats.add_latency(start_time_line, end_time_line);

                if (line_error_count > 5 && !config.verbose) {
                    std::cerr << "Thread " << thread_id << " ... and " << (line_error_count - 5)
                             << " more errors in line " << task.line_idx << std::endl;
                }

                completed_lines.fetch_add(1, std::memory_order_relaxed);

                if (config.verbose && completed_lines.load(std::memory_order_relaxed) % 100 == 0) {
                    std::cout << "Thread " << thread_id << " completed "
                             << completed_lines.load(std::memory_order_relaxed) << " lines" << std::endl;
                }
            }

            // Cleanup thread resources
            io_uring_queue_exit(&ring);
            free(buffer); // Use free for posix_memalign
            close(fd);
        });
    }

    // Wait for all threads to complete
    for (auto& thread : threads) {
        thread.join();
    }

    // End timing for overall throughput
    auto end_time_overall = std::chrono::high_resolution_clock::now();
    std::chrono::duration<double> elapsed = end_time_overall - start_time_overall;

    // Report overall results
    std::cout << "Read completed: " << completed_ops.load(std::memory_order_relaxed) << "/" << total_hash_ids
              << " operations across " << completed_lines.load(std::memory_order_relaxed) << "/" << lines_data.size()
              << " lines" << std::endl;
    std::cout << "Total time: " << elapsed.count() << " seconds" << std::endl;
    std::cout << "Throughput: " << (completed_ops.load(std::memory_order_relaxed) * config.kv_cache_size) / (1024.0 * 1024.0) / elapsed.count()
              << " MB/s" << std::endl;

    if (error_count.load(std::memory_order_relaxed) > 0) {
        std::cout << "Total errors: " << error_count.load(std::memory_order_relaxed) << std::endl;
    }

    // Print latency statistics
    op_latency_stats.print_stats("Individual Read Operations (io_uring)");
    line_latency_stats.print_stats("Line Processing (io_uring)");

    // Save detailed latency data if requested
    if (config.save_latency_data || config.verbose) {
        std::string op_latency_file = config.latency_output_dir + "/" +
                                     fs::path(config.output_file).filename().string() +
                                     ".read_iouring_mt_ops_latency.csv";
        op_latency_stats.save_to_csv(op_latency_file, "read_iouring_mt_operation");

        std::string line_latency_file = config.latency_output_dir + "/" +
                                       fs::path(config.output_file).filename().string() +
                                       ".read_iouring_mt_line_latency.csv";
        line_latency_stats.save_to_csv(line_latency_file, "read_iouring_mt_line");
    }
}

void benchmark_write_libc(const Config& config, uint64_t num_blocks) {
    std::cout << "Starting libc write benchmark with " << num_blocks << " blocks ("
              << config.block_size << " bytes each)..." << std::endl;
    // Open output file
    // Use open for consistency with O_DIRECT
    int fd = open_file_with_options(
        config.output_file,
        FileMode::WRITE,
        config.use_direct_io,
        config.fadvise_mode
    );
    if (fd < 0) {
        std::cerr << "Failed to open output file: " << strerror(errno) << std::endl;
        return;
    }

    // Allocate aligned memory for O_DIRECT compatibility
    uint8_t* buffer;
    if (posix_memalign((void**)&buffer, 512, config.block_size) != 0) {
        std::cerr << "Failed to allocate aligned buffer." << std::endl;
        close(fd);
        return;
    }

    // Fill buffer with test data
    create_test_data(buffer, config.block_size);



    // Create latency tracking structure and preallocate space
    LatencyStats latency_stats;
    latency_stats.reserve(num_blocks);

    // Store start times for each operation
    std::vector<std::chrono::high_resolution_clock::time_point> start_times(num_blocks);

    auto start_time_overall = std::chrono::high_resolution_clock::now();
    start_kutrace(config);

    uint64_t completed = 0;
    int error_count = 0;

    for (uint64_t i = 0; i < num_blocks; ++i) {
        start_times[i] = std::chrono::high_resolution_clock::now();
        if (config.kutrace) {
            kutrace::addname(KUTRACE_METHODNAME, i, "LibcWrite");
            kutrace::addevent(KUTRACE_RPCIDREQ, i);
            kutrace::mark_b("write");
            kutrace::mark_d(i);
        }

        // Use write() instead of fwrite()
        ssize_t written = write(fd, buffer, config.block_size);

        auto end_time = std::chrono::high_resolution_clock::now();

        if (config.kutrace) {
            kutrace::mark_c("/write");
        }

        if (written == config.block_size) {
            latency_stats.add_latency(start_times[i], end_time);
            completed++;
        } else {
            error_count++;
            if (config.verbose || error_count <= 5) {
                std::cerr << "IO operation " << i
                          << " failed with error: " << strerror(errno)
                          << std::endl;
            }
        }

    }
    if (config.kutrace) { kutrace::addevent(KUTRACE_RPCIDREQ, 0); }

    // End timing for overall throughput
    auto end_time_overall = std::chrono::high_resolution_clock::now();
    std::chrono::duration<double> elapsed = end_time_overall - start_time_overall;


    // Report results
    std::cout << "Write completed: " << completed << "/" << num_blocks << " operations" << std::endl;
    std::cout << "Total time: " << elapsed.count() << " seconds" << std::endl;
    std::cout << "Throughput: " << (completed * config.block_size) / (1024.0 * 1024.0) / elapsed.count()
              << " MB/s" << std::endl;

    if (error_count > 5 && !config.verbose) {
        std::cerr << "... and " << (error_count - 5) << " more errors" << std::endl;
    }

    // Print latency statistics
    latency_stats.print_stats("Write (libc)");

    // Save detailed latency data if requested
    if (config.save_latency_data || config.verbose) {
        std::string latency_file = config.latency_output_dir + "/" +
                                  fs::path(config.output_file).filename().string() +
                                  ".write_libc_latency.csv";
        latency_stats.save_to_csv(latency_file, "write_libc");
    }

    // Cleanup
    free(buffer);  // Use free() with posix_memalign()
    close(fd);
}



void benchmark_read_libc(const Config& config) {
     std::cout << "Starting multithreaded libc read benchmark with "
              << config.num_threads << " threads..." << std::endl;

    // Load lines with hash_ids from JSONL file
    std::vector<LineHashIds> lines_data = load_jsonl_lines(config.jsonl_file);
    if (lines_data.empty()) {
        std::cerr << "No valid lines with hash_ids found in " << config.jsonl_file << std::endl;
        return;
    }

    // Count total hash_ids and maximum per line
    size_t total_hash_ids = 0;
    size_t max_line_hash_count = 0;
    for (const auto& line : lines_data) {
        total_hash_ids += line.hash_ids.size();
        max_line_hash_count = std::max(max_line_hash_count, line.hash_ids.size());
    }

    std::cout << "Processing " << lines_data.size() << " lines with a total of "
              << total_hash_ids << " hash_ids entries" << std::endl;

    // Create task queue
    moodycamel::ConcurrentQueue<ReadTask> task_queue(lines_data.size());
    for (size_t i = 0; i < lines_data.size(); i++) {
        task_queue.enqueue({i});
    }

    // Atomics for progress tracking
    std::atomic<size_t> completed_lines(0);
    std::atomic<size_t> completed_ops(0);
    std::atomic<size_t> error_count(0);
    std::atomic<size_t> total_reads_submitted(0);


    // Latency stats
    LatencyStats op_latency_stats;
    LatencyStats line_latency_stats;
    op_latency_stats.reserve(total_hash_ids);
    line_latency_stats.reserve(lines_data.size());

    auto start_time_overall = std::chrono::high_resolution_clock::now();

    std::vector<std::thread> threads;

    start_kutrace(config);

    for (uint32_t thread_id = 0; thread_id < config.num_threads; thread_id++) {
        threads.emplace_back([&, thread_id]() {
            // Open input file (each thread gets its own fd)
            int fd = open_file_with_options(
                config.output_file,
                FileMode::READ,
                config.use_direct_io,  // Use direct IO setting
                config.fadvise_mode,
                thread_id
            );
            if (fd < 0) {
                std::cerr << "Thread " << thread_id << " failed to open input file." << std::endl;
                return;
            }
            // Buffer for reading (aligned for O_DIRECT)

            uint8_t* buffer;
            if (posix_memalign((void**)&buffer, 512, config.kv_cache_size) != 0) {
                std::cerr << "Thread " << thread_id << " failed to allocate aligned buffer" << std::endl;
                close(fd);
                return;
            }

            std::vector<std::chrono::high_resolution_clock::time_point> start_times(max_line_hash_count);

            // Process tasks
            ReadTask task;
            while (task_queue.try_dequeue(task)) {
                const auto& line = lines_data[task.line_idx];

                if (line.hash_ids.empty()) {
                    completed_lines++;
                    continue;
                }
                auto start_time_line = std::chrono::high_resolution_clock::now();

                int line_error_count = 0;
                size_t submitted_reads = 0;

                for (size_t i = 0; i < line.hash_ids.size(); i++) {
                    off_t offset = line.hash_ids[i] * config.kv_cache_size;
                    start_times[i] = std::chrono::high_resolution_clock::now();

                    auto submitted_read = total_reads_submitted.fetch_add(1, std::memory_order_relaxed);
                    if (config.kutrace) {
                       kutrace::addname(KUTRACE_METHODNAME, submitted_read, "LibcRead");
                       kutrace::addevent(KUTRACE_RPCIDREQ, submitted_read);
                       kutrace::mark_b("read");
                        kutrace::mark_d(submitted_read);
                    }

                    // Use pread for thread-safe reading
                    ssize_t read_count = pread(fd, buffer, config.kv_cache_size, offset);
                    submitted_reads++;

                    auto end_time = std::chrono::high_resolution_clock::now();

                    if (config.kutrace) {
                        kutrace::mark_c("/read");
                    }

                    if (static_cast<uint64_t>(read_count) == config.kv_cache_size) {
                        op_latency_stats.add_latency(start_times[i], end_time);
                        completed_ops++;
                    } else {
                        line_error_count++;
                        error_count++;
                         if (config.verbose || line_error_count <= 5) {
                             std::cerr<< "Thread " << thread_id << " IO operation at index " << i
                                         << " in line " << task.line_idx
                                         << " failed with error: " << strerror(errno)
                                         << std::endl;
                         }
                    }

                }
                if (config.kutrace) { kutrace::addevent(KUTRACE_RPCIDREQ, 0); }

                auto end_time_line = std::chrono::high_resolution_clock::now();
                line_latency_stats.add_latency(start_time_line, end_time_line);
                completed_lines++;
            }

            free(buffer);  // Clean up aligned buffer
            close(fd);
        });
    }
    // Wait for all threads
    for (auto& thread : threads) {
        thread.join();
    }

    auto end_time_overall = std::chrono::high_resolution_clock::now();
    std::chrono::duration<double> elapsed = end_time_overall - start_time_overall;

    std::cout << "Read completed: " << completed_ops << "/" << total_hash_ids
              << " operations across " << completed_lines << "/" << lines_data.size()
              << " lines" << std::endl;
    std::cout << "Total time: " << elapsed.count() << " seconds" << std::endl;
    std::cout << "Throughput: " << (completed_ops * config.kv_cache_size) / (1024.0 * 1024.0) / elapsed.count()
              << " MB/s" << std::endl;
     if (error_count > 0) {
        std::cout << "Total errors: " << error_count << std::endl;
    }

    // Print latency statistics
    op_latency_stats.print_stats("Individual Read Operations (libc)");
    line_latency_stats.print_stats("Line Processing (libc)");

    // Save detailed latency data if requested
    if (config.save_latency_data || config.verbose) {
        std::string op_latency_file = config.latency_output_dir + "/" +
                                     fs::path(config.output_file).filename().string() +
                                     ".read_libc_mt_ops_latency.csv";
        op_latency_stats.save_to_csv(op_latency_file, "read_libc_mt_operation");

        std::string line_latency_file = config.latency_output_dir + "/" +
                                       fs::path(config.output_file).filename().string() +
                                       ".read_libc_mt_line_latency.csv";
        line_latency_stats.save_to_csv(line_latency_file, "read_libc_mt_line");
    }

}

int main(int argc, char* argv[]) {
    Config config;

    // Setup command line options with cxxopts
    cxxopts::Options options("3fs_benchmark", "Benchmark utility for 3FS User Space Ring Based IO (USRBIO)");

    options.add_options()
        ("j,jsonl", "Path to JSONL file containing hash IDs", cxxopts::value<std::string>())
        ("o,output", "Path to output file for benchmarking (must be on a 3FS mount)", cxxopts::value<std::string>())
        ("l,mount", "3FS mount point", cxxopts::value<std::string>()->default_value(DEFAULT_MOUNT_POINT))
        ("s,kv-size", "KV cache entry size in bytes", cxxopts::value<uint64_t>()->default_value(std::to_string(DEFAULT_KV_CACHE_SIZE)))
        ("b,block-size", "Block size for I/O operations in bytes", cxxopts::value<uint64_t>()->default_value(std::to_string(DEFAULT_BLOCK_SIZE)))
        ("i,io-depth", "I/O depth for batching requests", cxxopts::value<int>()->default_value(std::to_string(DEFAULT_IO_DEPTH)))
        ("skip-write", "Skip write benchmark", cxxopts::value<bool>()->default_value("false"))
        ("skip-read", "Skip read benchmark", cxxopts::value<bool>()->default_value("false"))
        ("latency-dir", "Directory to store latency CSV files", cxxopts::value<std::string>()->default_value("./"))
        ("save-latency", "Save detailed latency data to CSV files", cxxopts::value<bool>()->default_value("false"))
        ("t,num-threads", "Number of threads", cxxopts::value<uint32_t>()->default_value(std::to_string(std::thread::hardware_concurrency())))
        ("v,verbose", "Enable verbose output", cxxopts::value<bool>()->default_value("false"))
        ("m,mode", "Benchmark mode (usrbio, io_uring, or libc)", cxxopts::value<std::string>()->default_value("usrbio"))
        ("k,kutrace", "Run KUTrace", cxxopts::value<bool>()->default_value("false"))
        ("kutrace-control", "Number of threads", cxxopts::value<int>()->default_value(std::to_string(DO_IPC | DO_WRAP)))
        ("direct-io", "Use O_DIRECT flag to bypass page cache", cxxopts::value<bool>()->default_value("true"))
        ("fadvise", "Set fadvise hint (normal, sequential, random, willneed, dontneed, noreuse)", cxxopts::value<std::string>()->default_value("normal"))
        ("h,help", "Print usage information")
    ;

    try {
        auto result = options.parse(argc, argv);

        if (result.count("help")) {
            std::cout << options.help() << std::endl;
            return 0;
        }

        // Required arguments
        if (!result.count("jsonl") || !result.count("output")) {
            std::cerr << "Error: JSONL file and output file are required arguments" << std::endl;
            std::cout << options.help() << std::endl;
            return 1;
        }

        // Parse configuration
        config.jsonl_file = result["jsonl"].as<std::string>();
        config.output_file = result["output"].as<std::string>();
        config.mount_point = result["mount"].as<std::string>();
        config.kv_cache_size = result["kv-size"].as<uint64_t>();
        config.block_size = result["block-size"].as<uint64_t>();
        config.io_depth = result["io-depth"].as<int>();
        config.skip_write = result["skip-write"].as<bool>();
        config.skip_read = result["skip-read"].as<bool>();
        config.verbose = result["verbose"].as<bool>();
        config.save_latency_data = result["save-latency"].as<bool>();
        config.latency_output_dir = result["latency-dir"].as<std::string>();
        config.num_threads = result["num-threads"].as<uint32_t>();
        config.use_direct_io = result["direct-io"].as<bool>();
        config.kutrace = result["kutrace"].as<bool>();
        config.kutrace_control = result["kutrace-control"].as<int>();
        config.program_name = argv[0];

        // Parse fadvise mode
        std::string fadvise_str = result["fadvise"].as<std::string>();
        std::transform(fadvise_str.begin(), fadvise_str.end(), fadvise_str.begin(), ::tolower);

        if (fadvise_str == "sequential") {
            config.fadvise_mode = POSIX_FADV_SEQUENTIAL;
        } else if (fadvise_str == "random") {
            config.fadvise_mode = POSIX_FADV_RANDOM;
        } else if (fadvise_str == "willneed") {
            config.fadvise_mode = POSIX_FADV_WILLNEED;
        } else if (fadvise_str == "dontneed") {
            config.fadvise_mode = POSIX_FADV_DONTNEED;
        } else if (fadvise_str == "noreuse") {
            config.fadvise_mode = POSIX_FADV_NOREUSE;
        } else {
            config.fadvise_mode = POSIX_FADV_NORMAL;
        }

        // Parse benchmark mode
        std::string mode_str = result["mode"].as<std::string>();
        std::transform(mode_str.begin(), mode_str.end(), mode_str.begin(), ::tolower);

        if (mode_str == "io_uring" || mode_str == "iouring") {
            config.io_uring_available = check_io_uring_available();
            if (config.io_uring_available) {
                config.mode = BenchmarkMode::IO_URING;
            } else {
                std::cerr << "io_uring requested but not available on this system. Using USRBIO instead." << std::endl;
                config.mode = BenchmarkMode::USRBIO;
            }
        } else if (mode_str == "libc") {
            config.mode = BenchmarkMode::LIBC;
        }
        else {
            config.mode = BenchmarkMode::USRBIO;
        }

        // Validate configuration
        if (config.kv_cache_size == 0) {
            std::cerr << "Invalid KV cache size. Using default: "
                      << DEFAULT_KV_CACHE_SIZE << std::endl;
            config.kv_cache_size = DEFAULT_KV_CACHE_SIZE;
        }

        if (config.block_size == 0) {
            std::cerr << "Invalid block size. Using default: "
                      << DEFAULT_BLOCK_SIZE << std::endl;
            config.block_size = DEFAULT_BLOCK_SIZE;
        }

        // Create latency output directory if it doesn't exist
        if (config.save_latency_data || config.verbose) {
            try {
                fs::create_directories(config.latency_output_dir);
            } catch (const std::exception& e) {
                std::cerr << "Failed to create latency output directory: " << e.what() << std::endl;
                std::cerr << "Using current directory for latency output." << std::endl;
                config.latency_output_dir = "./";
            }
        }

        // Ensure output file is on 3FS mount point *only* for 3FS modes.
        if (!config.skip_write && !config.skip_read && (config.mode == BenchmarkMode::USRBIO || config.mode == BenchmarkMode::IO_URING)) {
            fs::path output_path = config.output_file;
            fs::path mount_path = config.mount_point;

            if (!output_path.is_absolute()) {
                output_path = fs::absolute(output_path);
            }

            if (!mount_path.is_absolute()) {
                mount_path = fs::absolute(mount_path);
            }

            std::string output_str = output_path.string();
            std::string mount_str = mount_path.string();

            if (output_str.find(mount_str) != 0) {
                std::cerr << "Warning: Output file doesn't appear to be on 3FS mount point." << std::endl;
                std::cerr << "         Mount point: " << mount_str << std::endl;
                std::cerr << "         Output file: " << output_str << std::endl;
            }
        }

    } catch (const std::exception& e) {
        std::cerr << "Error parsing options: " << e.what() << std::endl;
        std::cout << options.help() << std::endl;
        return 1;
    }

    // Print configuration
    std::cout << "Configuration:" << std::endl;
    std::cout << "  JSONL file: " << config.jsonl_file << std::endl;
    std::cout << "  Output file: " << config.output_file << std::endl;
    std::cout << "  Mount point: " << config.mount_point << std::endl;
    std::cout << "  KV cache size: " << config.kv_cache_size << " bytes" << std::endl;
    std::cout << "  Block size: " << config.block_size << " bytes" << std::endl;
    std::cout << "  IO depth: " << config.io_depth << std::endl;
    std::cout << "  Mode: " << (config.mode == BenchmarkMode::USRBIO ? "USRBIO" :
                                 (config.mode == BenchmarkMode::IO_URING ? "IO_URING" : "LIBC")) << std::endl;
    std::cout << "  IO_URING available: " << (config.io_uring_available ? "Yes" : "No") << std::endl;
    std::cout << "  Save latency data: " << (config.save_latency_data ? "Yes" : "No") << std::endl;
    std::cout << "  Latency output directory: " << config.latency_output_dir << std::endl;
     std::cout << "  Number of Threads: " << config.num_threads << std::endl;
    std::cout << "  I/O mode: " << (config.use_direct_io ? "Direct I/O (bypass page cache)" : "Buffered I/O (use page cache)") << std::endl;
    std::cout << "  Kutrace: " << (config.kutrace ? "Yes" : "No") << std::endl;
    if (!config.use_direct_io) {
        std::cout << "  Fadvise mode: ";
        switch (config.fadvise_mode) {
            case POSIX_FADV_NORMAL: std::cout << "NORMAL"; break;
            case POSIX_FADV_SEQUENTIAL: std::cout << "SEQUENTIAL"; break;
            case POSIX_FADV_RANDOM: std::cout << "RANDOM"; break;
            case POSIX_FADV_WILLNEED: std::cout << "WILLNEED"; break;
            case POSIX_FADV_DONTNEED: std::cout << "DONTNEED"; break;
            case POSIX_FADV_NOREUSE: std::cout << "NOREUSE"; break;
            default: std::cout << "UNKNOWN"; break;
        }
        std::cout << std::endl;
    }

    // Find max hash ID from JSONL file
    uint64_t max_hash_id = find_max_hash_id(config.jsonl_file);
    if (max_hash_id == 0) {
        std::cerr << "No valid hash IDs found in " << config.jsonl_file << std::endl;
        return 1;
    }

    std::cout << "Maximum hash ID found: " << max_hash_id << std::endl;

    // Calculate file size based on max hash ID and KV cache size
    uint64_t total_size = (max_hash_id + 1) * config.kv_cache_size;
    uint64_t num_blocks = (total_size + config.block_size - 1) / config.block_size;

    std::cout << "Total size to benchmark: " << total_size << " bytes ("
              << total_size / (1024 * 1024) << " MB)" << std::endl;
    std::cout << "Number of blocks: " << num_blocks << std::endl;

    // Run benchmarks
    if (!config.skip_write) {
        if (config.mode == BenchmarkMode::USRBIO) {
            benchmark_write_3fs(config, num_blocks);
        } else if (config.mode == BenchmarkMode::IO_URING && config.io_uring_available) {
            benchmark_write_io_uring(config, num_blocks);
        } else if (config.mode == BenchmarkMode::LIBC) {
            benchmark_write_libc(config, num_blocks);
        }
    } else {
        std::cout << "Skipping write benchmark." << std::endl;
    }

    if (!config.skip_read) {
        if (config.mode == BenchmarkMode::USRBIO) {
            benchmark_read_3fs(config);
        } else if (config.mode == BenchmarkMode::IO_URING && config.io_uring_available) {
            benchmark_read_io_uring(config);
        }
        else if (config.mode == BenchmarkMode::LIBC){
            benchmark_read_libc(config);
        }
    } else {
        std::cout << "Skipping read benchmark." << std::endl;
    }

    stop_kutrace(config);

    return 0;
}