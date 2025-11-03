#pragma once

// rpc_logger.h
// Simple header-only RPC logging API to track client-server communications
// Based on BinaryLogRecord structure

#include <string>
#include <string_view>
#include <cstdint>
#include <cinttypes>
#include <cstring>
#include <fstream>
#include <iostream>
#include <cmath>
#include <iomanip>
#include <sstream>
#include <vector>
#include <sys/time.h>
#include <netinet/in.h>
#include <arpa/inet.h>
#include <mutex>
#include <atomic>
#include <cstdlib> // For std::getenv
#include <algorithm>
#include <thread>
#include <chrono>
#include <thread>
#include <chrono>
#include <filesystem>

// #include <signal.h>
#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Wunused-parameter"
#pragma GCC diagnostic ignored "-Wgnu-zero-variadic-macro-arguments"
#pragma GCC diagnostic ignored "-Wunused-private-field"
#pragma GCC diagnostic ignored "-Wc99-extensions"
#pragma GCC diagnostic ignored "-Wzero-length-array"
#pragma GCC diagnostic ignored "-Wunused-variable"
#pragma GCC diagnostic ignored "-Wdeprecated-volatile"
#include "NanoLogCpp17.h"
#pragma GCC diagnostic pop

// Fetch it
// wget https://raw.githubusercontent.com/cameron314/concurrentqueue/refs/heads/master/concurrentqueue.h

// Runtime environment variable checks with caching
namespace kutrace {
    inline bool use_rpc_background_thread() {
        static bool cached = false;
        static bool result = false;
        if (!cached) {
            const char* env_val = std::getenv("KUTRACE_RPC_USE_BACKGROUND_THREAD");
            result = (env_val != nullptr && std::string(env_val) != "0" && std::string(env_val) != "false");
            cached = true;
        }
        return result;
    }
    
    inline bool use_nanolog_background_thread() {
        static bool cached = false;
        static bool result = false;
        if (!cached) {
            const char* env_val = std::getenv("KUTRACE_NANOLOG_USE_BACKGROUND_THREAD");
            result = (env_val != nullptr && std::string(env_val) != "0" && std::string(env_val) != "false");
            cached = true;
        }
        return result;
    }
}

// Always include concurrentqueue since we might need it at runtime
#undef BLOCK_SIZE
#include "concurrentqueue/concurrentqueue.h"

#define KUTRACE_RPC_ENABLE
#define KUTRACE_NANOLOG_ENABLE

namespace kutrace {

// Constants
const int kMaxLogDataSize = 4;
const int kMaxMethodNameSize = 64;

#ifndef KUTRACE_RPC_TYPES_DEFINED
#define KUTRACE_RPC_TYPES_DEFINED

// RPC types
enum class RPCType : uint16_t {
    ReqSend = 0,
    ReqRcv,
    RespSend,
    RespRcv,
    Text,
    NumType
};

// RPC status
enum class RPCStatus : uint32_t {
    Success = 0,
    Fail,
    TooBusy,
    NumStatus
};

// Simple structure to represent an IP address and port
struct NetworkAddress {
    uint32_t ip;   // IPv4 address in network byte order
    uint16_t port; // Port number
    
    NetworkAddress() : ip(0), port(0) {}
    
    NetworkAddress(uint32_t ip_addr, uint16_t port_num) : ip(ip_addr), port(port_num) {}
    
    NetworkAddress(const std::string& ip_str, uint16_t port_num) : port(port_num) {
        struct in_addr addr;
        inet_aton(ip_str.c_str(), &addr);
        ip = addr.s_addr;
    }
    
    std::string to_string() const {
        struct in_addr addr;
        addr.s_addr = ip;
        std::stringstream ss;
        ss << inet_ntoa(addr) << ":" << port;
        return ss.str();
    }
    
    // Just the IP part as a string
    std::string ip_to_string() const {
        struct in_addr addr;
        addr.s_addr = ip;
        return std::string(inet_ntoa(addr));
    }
};

// Message data structure for simplifying API calls
struct RPCMessage {
    const uint8_t* data;
    uint32_t length;
    
    RPCMessage() : data(nullptr), length(0) {}
    
    RPCMessage(const uint8_t* data_ptr, uint32_t data_len) : data(data_ptr), length(data_len) {}
    
    RPCMessage(std::string_view str) 
        : data(reinterpret_cast<const uint8_t*>(str.data())), length(str.length()) {}
    
    RPCMessage(const std::string& str) 
        : data(reinterpret_cast<const uint8_t*>(str.data())), length(str.length()) {}
    
    RPCMessage(const char* str) 
        : data(reinterpret_cast<const uint8_t*>(str)), length(strlen(str)) {}
};

#endif

// Binary log record structure (96 bytes)
typedef struct {
    uint32_t rpcid;
    uint32_t parent;
    int64_t req_send_timestamp;  // usec since the epoch, client clock
    int64_t req_rcv_timestamp;   // usec since the epoch, server clock
    int64_t resp_send_timestamp; // usec since the epoch, server clock
    int64_t resp_rcv_timestamp;  // usec since the epoch, client clock
    // 40 bytes

    uint32_t client_ip;
    uint32_t server_ip;
    uint16_t client_port;
    uint16_t server_port;
    uint8_t lglen1;              // 10 * lg(request data length in bytes)
    uint8_t lglen2;              // 10 * lg(response data length in bytes)
    uint16_t type;               // An RPCType
    // 16 bytes

    char method[kMaxMethodNameSize];
    // 64 bytes

    uint32_t status;             // 0 = success, other = error code
    uint32_t datalength;         // full length transmitted
    // 72 bytes to here

    uint8_t data[kMaxLogDataSize]; // truncated, zero filled
    // 96 bytes
} BinaryLogRecord;

// Simple header-only RPC Logger class
class RPCLogger {
public:
    RPCLogger() : m_ready(false) {}

    // Constructor - opens log file
    RPCLogger(const std::string& filename) : m_ready(false) {
        open(filename);
    }
    
    // Destructor - closes log file
    ~RPCLogger() {
        m_ready = false;
        if (worker_thread.joinable()) {
            worker_thread.join();
        }
        if (m_logFile.is_open()) {
            m_logFile.close();
        }
    }
    
    // Check if logger is ready (file opened successfully)
    bool is_ready() const { return m_ready; }

    void open(const std::string& filename, std::size_t batch_size = 10000, std::size_t timeout_ms = 10) {
        std::lock_guard<std::mutex> l(m);
        
        // If there's already a worker thread running, stop it first
        if (use_rpc_background_thread() && worker_thread.joinable()) {
            m_ready = false;  // Signal the existing thread to stop
            worker_thread.join();  // Wait for it to finish
        }
        
        m_logFile.open(filename, std::ios::out | std::ios::binary | std::ios::trunc);
        if (m_logFile.is_open()) {
            m_ready = true;
        } else {
            std::cerr << "Failed to open log file: " << filename << std::endl;
        }

        if (use_rpc_background_thread()) {
            worker_thread = std::thread([this, batch_size, timeout_ms]() {
#if defined(__linux__) || defined(__unix__)
            pthread_setname_np(pthread_self(), "RPCLoggerWorker");
#endif
            std::vector<BinaryLogRecord> batch_records;
            batch_records.resize(batch_size);
            std::size_t index = 0;
            auto start = std::chrono::steady_clock::now();
            while (m_ready) {
                if (queue.try_dequeue(batch_records[index])) {
                    index++;
                } else {
                    // Sleep for a bit
                    std::this_thread::sleep_for(std::chrono::nanoseconds(500));
                }
                auto end = std::chrono::steady_clock::now();
                auto elapsed = std::chrono::duration_cast<std::chrono::milliseconds>(end - start);
                // Flush
                if (should_flush || index == batch_size || elapsed.count() > static_cast<long>(timeout_ms)) {
                    m_logFile.write(reinterpret_cast<const char*>(batch_records.data()), index * sizeof(BinaryLogRecord));
                    m_logFile.flush();
                    index = 0;
                    start = end;
                    // should_flush.store(true, std::memory_order_relaxed);
                }
            }
            });
        }        
    }

    // Client-side logging
    uint64_t log_client_send(
        uint32_t rpcid,
        uint32_t parent,
        const NetworkAddress& client,
        const NetworkAddress& server,
        std::string_view method,
        const RPCMessage& message
    ) {
        BinaryLogRecord record;
        init_record(record, rpcid, parent, client, server, method, 0, message);
        
        // Set specific fields for this log type
        record.type = static_cast<uint16_t>(RPCType::ReqSend);
        record.req_send_timestamp = get_current_usec();
        
        write_record(record);
        return record.req_send_timestamp;
    }
    
    void log_client_recv(
        uint32_t rpcid,
        uint32_t parent,
        const NetworkAddress& client,
        const NetworkAddress& server,
        std::string_view method,
        RPCStatus status,
        const RPCMessage& message,
        int64_t req_send_time,
        int64_t req_rcv_time,
        int64_t resp_send_time
    ) {
        BinaryLogRecord record;
        init_record(record, rpcid, parent, client, server, method, 
                  static_cast<uint32_t>(status), message);
        
        // Set specific fields for this log type
        record.type = static_cast<uint16_t>(RPCType::RespRcv);
        record.req_send_timestamp = req_send_time;
        record.req_rcv_timestamp = req_rcv_time;
        record.resp_send_timestamp = resp_send_time;
        record.resp_rcv_timestamp = get_current_usec();
        record.lglen2 = calculate_ten_lg(message.length);
        
        write_record(record);
    }
    
    // Server-side logging
    void log_server_recv(
        uint32_t rpcid,
        uint32_t parent,
        const NetworkAddress& client,
        const NetworkAddress& server,
        std::string_view method,
        const RPCMessage& message,
        int64_t req_send_time
    ) {
        BinaryLogRecord record;
        init_record(record, rpcid, parent, client, server, method, 0, message);
        
        // Set specific fields for this log type
        record.type = static_cast<uint16_t>(RPCType::ReqRcv);
        record.req_send_timestamp = req_send_time;
        record.req_rcv_timestamp = get_current_usec();
        
        write_record(record);
    }

    void log_server_send(
        uint32_t rpcid,
        uint32_t parent,
        const NetworkAddress& client,
        const NetworkAddress& server,
        std::string_view method,
        RPCStatus status,
        const RPCMessage& message,
        int64_t req_send_time,
        int64_t req_rcv_time
    ) {
        BinaryLogRecord record;
        init_record(record, rpcid, parent, client, server, method, 
                  static_cast<uint32_t>(status), message);
        
        // Set specific fields for this log type
        record.type = static_cast<uint16_t>(RPCType::RespSend);
        record.req_send_timestamp = req_send_time;
        record.req_rcv_timestamp = req_rcv_time;
        record.resp_send_timestamp = get_current_usec();
        record.lglen2 = calculate_ten_lg(message.length);
        
        write_record(record);
    }
    
    // Generate reports
    static bool generate_text_report(const std::string& binary_file, const std::string& text_file) {
        std::ifstream in_file(binary_file, std::ios::in | std::ios::binary);
        if (!in_file.is_open()) {
            std::cerr << "Failed to open binary log file: " << binary_file << std::endl;
            return false;
        }
        
        std::ofstream out_file(text_file);
        if (!out_file.is_open()) {
            std::cerr << "Failed to open text output file: " << text_file << std::endl;
            in_file.close();
            return false;
        }
        
        // Write header
        out_file << "RPC ID,Parent,Type,Method,Status,Client,Server,";
        out_file << "REQ Send Time,REQ Recv Time,RESP Send Time,RESP Recv Time,";
        out_file << "Data Length,Data Preview" << std::endl;
        
        BinaryLogRecord record;
        while (in_file.read(reinterpret_cast<char*>(&record), sizeof(BinaryLogRecord))) {
            out_file << record.rpcid << ",";
            out_file << record.parent << ",";
            out_file << type_to_string(record.type) << ",";
            out_file << std::string(record.method, std::min(size_t(8), strlen(record.method))) << ",";
            out_file << status_to_string(record.status) << ",";
            
            NetworkAddress client(record.client_ip, record.client_port);
            NetworkAddress server(record.server_ip, record.server_port);
            out_file << client.to_string() << ",";
            out_file << server.to_string() << ",";
            
            out_file << format_timestamp(record.req_send_timestamp) << ",";
            out_file << format_timestamp(record.req_rcv_timestamp) << ",";
            out_file << format_timestamp(record.resp_send_timestamp) << ",";
            out_file << format_timestamp(record.resp_rcv_timestamp) << ",";
            out_file << record.datalength << ",";
            
            // Print data as hex representation for binary data or as text if printable
            out_file << "\"";
            bool is_printable = true;
            for (int i = 0; i < std::min(kMaxLogDataSize, int(record.datalength)); i++) {
                if (record.data[i] < 32 || record.data[i] > 126) {
                    is_printable = false;
                    break;
                }
            }
            
            if (is_printable) {
                for (int i = 0; i < std::min(kMaxLogDataSize, int(record.datalength)); i++) {
                    out_file << (char)record.data[i];
                }
            } else {
                for (int i = 0; i < std::min(kMaxLogDataSize, int(record.datalength)); i++) {
                    out_file << std::hex << std::setfill('0') << std::setw(2) 
                             << (int)record.data[i] << " ";
                }
                out_file << std::dec;
            }
            out_file << "\"";
            
            out_file << std::endl;
        }
        
        in_file.close();
        out_file.close();
        return true;
    }
    
    static bool generate_json_report(const std::string& binary_file, const std::string& json_file, const char* title = "RPC Transactions") {
        std::ifstream in_file(binary_file, std::ios::in | std::ios::binary);
        if (!in_file.is_open()) {
            std::cerr << "Failed to open binary log file: " << binary_file << std::endl;
            return false;
        }
        
        std::ofstream out_file(json_file);
        if (!out_file.is_open()) {
            std::cerr << "Failed to open JSON output file: " << json_file << std::endl;
            in_file.close();
            return false;
        }
        
        // Read the first record to get the base time
        BinaryLogRecord first_record;
        int64_t basetime = 0;
        
        // First pass to find the first valid timestamp for basetime
        in_file.seekg(0);
        while (in_file.read(reinterpret_cast<char*>(&first_record), sizeof(BinaryLogRecord))) {
            if (first_record.req_send_timestamp != 0) {
                // Round down usec time to multiple of one minute
                basetime = (first_record.req_send_timestamp / 60000000) * 60000000;
                break;
            }
        }
        
        if (basetime == 0) {
            std::cerr << "No valid timestamps found in log file" << std::endl;
            in_file.close();
            out_file.close();
            return false;
        }
        
        // Write JSON header
        out_file << "  {\n";
        out_file << " \"Comment\" : \"V4 flat RPCs\",\n";
        out_file << " \"axisLabelX\" : \"Time (sec)\",\n";
        out_file << " \"axisLabelY\" : \"RPC Number\",\n";
        out_file << " \"deltaT23\" : 0,\n";
        out_file << " \"flags\" : 0,\n";
        out_file << " \"gbs\" : 1,\n";
        out_file << " \"shortMulX\" : 1,\n";
        out_file << " \"shortUnitsX\" : \"s\",\n";
        out_file << " \"thousandsX\" : 1000,\n";
        out_file << " \"title\" : \"" << (title ? title : "RPC Transactions") << "\",\n";
        out_file << " \"tracebase\" : \"" << format_seconds_date_time(basetime / 1000000) << "\",\n";
        out_file << " \"version\" : 4,\n";
        out_file << "\"events\" : [\n";
        
        // Second pass to write all records
        in_file.clear();
        in_file.seekg(0);
        
        BinaryLogRecord record;
        int record_count = 0;
        const int kMissingTime = 2; // Assumed time for missing timestamps (μs)
        
        while (in_file.read(reinterpret_cast<char*>(&record), sizeof(BinaryLogRecord))) {
            bool dumpme = false;
            if (record.type == static_cast<uint16_t>(RPCType::RespRcv)) dumpme = true;  // Complete transactions only by default
            
            if (dumpme) {
                // Fill in missing times and ensure they're non-decreasing
                
                // Estimated network transmission times
                int64_t est_req_usec = rpc_msglen_to_usec(record.lglen1);
                int64_t est_resp_usec = rpc_msglen_to_usec(record.lglen2);
                
                // Fill in any missing times (incomplete RPCs)
                if (record.req_rcv_timestamp == 0) {
                    record.req_rcv_timestamp = record.req_send_timestamp + est_req_usec + kMissingTime;
                }
                
                if (record.resp_send_timestamp == 0) {
                    record.resp_send_timestamp = record.req_rcv_timestamp + kMissingTime;
                }
                
                if (record.resp_rcv_timestamp == 0) {
                    record.resp_rcv_timestamp = record.req_send_timestamp + 
                        (record.resp_send_timestamp - record.req_rcv_timestamp) + 
                        est_req_usec + kMissingTime + est_resp_usec + kMissingTime;
                }
                
                // Ensure times are non-decreasing
                record.req_rcv_timestamp = max(record.req_rcv_timestamp, record.req_send_timestamp);
                record.resp_send_timestamp = max(record.resp_send_timestamp, record.req_rcv_timestamp);
                record.resp_rcv_timestamp = max(record.resp_rcv_timestamp, record.resp_send_timestamp);
                
                // Format as JSON
                if (record_count > 0) {
                    out_file << ",\n";
                }
                
                // Format exactly like PrintLogRecordAsJson
                out_file << "[";
                out_file << format_usec_time(record.req_send_timestamp - basetime) << ", ";
                out_file << format_usec_time(record.req_rcv_timestamp - basetime) << ", ";
                out_file << format_usec_time(record.resp_send_timestamp - basetime) << ", ";
                out_file << format_usec_time(record.resp_rcv_timestamp - basetime) << ", ";
                
                // Format IP addresses
                NetworkAddress client(record.client_ip, record.client_port);
                NetworkAddress server(record.server_ip, record.server_port);
                out_file << "\"" << client.ip_to_string() << "\", ";
                out_file << "\"" << server.ip_to_string() << "\", ";
                
                out_file << format_lglen(record.lglen1) << ", ";
                out_file << format_lglen(record.lglen2) << ", ";
                out_file << record.rpcid << ", ";
                out_file << record.parent << ", ";
                
                out_file << "\"" << type_to_string(record.type) << "\", ";
                out_file << "\"" << format_method(record.method) << "\", ";
                out_file << "\"" << status_to_string(record.status) << "\", ";
                
                out_file << record.datalength << ", ";
                out_file << "\"" << format_data(record.data, kMaxLogDataSize, record.datalength) << "\"";
                
                out_file << "]";
                record_count++;
            }
        }
        
        // Close the JSON
        if (record_count > 0) {
            out_file << ",\n";
        }
        out_file << "[999.0, 0.0, 0.0, 0.0, \"\", \"\", 0.0, 0.0, 0, 0, \"\", \"\", \"\", 0, \"\"]\n";
        out_file << "]}\n";
        
        in_file.close();
        out_file.close();
        return true;
    }
    
    // Helper to get current time in microseconds
    static int64_t get_current_usec() {
        // return std::chrono::steady_clock::now().time_since_epoch().count();
        struct timeval tv;
        gettimeofday(&tv, NULL);
        return (int64_t)tv.tv_sec * 1000000 + tv.tv_usec;
    }
    
    // Helper to calculate 10 * log2(x)
    static uint8_t calculate_ten_lg(uint32_t x) {
        if (x == 0) return 0;
        
        // Calculate floor(log2(x))
        int32_t floorLog2 = 0;
        uint32_t temp = x;
        while (temp > 1) {
            temp >>= 1;
            floorLog2++;
        }
        
        // Calculate 10 * log2(x) - simplified approach
        double exactLog2 = log2(x);
        return static_cast<uint8_t>(exactLog2 * 10.0 + 0.5); // Round to nearest integer
    }

#ifdef KUTRACE_RPC_ENABLE
    static RPCLogger* get() {
        static RPCLogger logger;
        const char* rpc_file = std::getenv("HF3FS_ENABLE_RPC_LOGGING_FILE");
        if (rpc_file) {
            if (!logger.is_ready()) {
                logger.open(rpc_file);
            }
            return &logger;
        }
        return nullptr;
    }
#endif

private:
    std::fstream m_logFile;
    std::atomic<bool> m_ready = false;
    inline static std::mutex m;
    // Always available for runtime switching
    std::atomic<bool> should_flush = false;
    moodycamel::ConcurrentQueue<BinaryLogRecord> queue;
    std::thread worker_thread;

    // 2**0.0 through 2**0.9
    static constexpr double kPowerTwoTenths[10] = {
        1.0000, 1.0718, 1.1487, 1.2311, 1.3195, 
        1.4142, 1.5157, 1.6245, 1.7411, 1.8661
    };
    
    // Initialize a record with common fields
    void init_record(BinaryLogRecord& record, 
                    uint32_t rpcid, 
                    uint32_t parent,
                    const NetworkAddress& client,
                    const NetworkAddress& server,
                    std::string_view method, 
                    uint32_t status,
                    const RPCMessage& message) {
        // Clear the record first
        std::memset(&record, 0, sizeof(BinaryLogRecord));
        
        // Set the common fields
        record.rpcid = rpcid;
        record.parent = parent;
        record.client_ip = client.ip;
        record.client_port = client.port;
        record.server_ip = server.ip;
        record.server_port = server.port;
        record.status = status;
        record.datalength = message.length;
        
        // Copy method name (truncate or zero-pad to 8 bytes)
        size_t method_len = std::min(method.length(), static_cast<size_t>(kMaxMethodNameSize));
        std::memcpy(record.method, method.data(), method_len);
        if (method_len < kMaxMethodNameSize) {
            std::memset(record.method + method_len, 0, kMaxMethodNameSize - method_len);
        }
        
        // Calculate log length
        record.lglen1 = calculate_ten_lg(message.length);
        
        // Copy data (truncate if necessary)
        uint32_t copyLen = (message.length < kMaxLogDataSize) ? message.length : kMaxLogDataSize;
        if (message.data != nullptr && copyLen > 0) {
            std::memcpy(record.data, message.data, copyLen);
        }
    }
    
    // Write record to file
    void write_record(const BinaryLogRecord& record) {
        if (m_ready) {
            if (use_rpc_background_thread()) {
                queue.enqueue(record);
            } else {
                std::lock_guard<std::mutex> l(m);
                m_logFile.write(reinterpret_cast<const char*>(&record), sizeof(BinaryLogRecord));
                m_logFile.flush();
            }
        }
    }
    
    // Helper functions for formatting
    
    // Format timestamp in human-readable form
    static std::string format_timestamp(int64_t usec) {
        if (usec == 0) return "0";
        
        time_t seconds = usec / 1000000;
        int microsec = usec % 1000000;
        
        struct tm* timeinfo = localtime(&seconds);
        
        char buffer[30];
        strftime(buffer, sizeof(buffer), "%Y-%m-%d %H:%M:%S", timeinfo);
        
        std::stringstream ss;
        ss << buffer << "." << std::setfill('0') << std::setw(6) << microsec;
        return ss.str();
    }
    
    // Format time in usecs as "  n.dddddd"
    static std::string format_usec_time(int64_t usec) {
        if (usec == 0) return "  0.000000";
        
        int32_t seconds = usec / 1000000;
        int32_t microsec = usec % 1000000;
        
        std::stringstream ss;
        ss << std::setw(3) << seconds << "." << std::setfill('0') << std::setw(6) << microsec;
        return ss.str();
    }
    
    // Convert type to string
    static std::string type_to_string(uint16_t type_val) {
        RPCType type = static_cast<RPCType>(type_val);
        switch (type) {
            case RPCType::ReqSend: return "ReqSend";
            case RPCType::ReqRcv: return "ReqRcv";
            case RPCType::RespSend: return "RespSend";
            case RPCType::RespRcv: return "RespRcv";
            case RPCType::Text: return "Text";
            default: return "Unknown";
        }
    }
    
    // Convert status to string
    static std::string status_to_string(uint32_t status_val) {
        if (status_val < static_cast<uint32_t>(RPCStatus::NumStatus)) {
            RPCStatus status = static_cast<RPCStatus>(status_val);
            switch (status) {
                case RPCStatus::Success: return "Success";
                case RPCStatus::Fail: return "Fail";
                case RPCStatus::TooBusy: return "TooBusy";
                default: return "Unknown";
            }
        }
        return "Status " + std::to_string(status_val);
    }
    
    // Format log length as "n.d"
    static std::string format_lglen(uint8_t len) {
        std::stringstream ss;
        ss << len / 10 << "." << len % 10;
        return ss.str();
    }
    
    // Format method with trailing zero
    static std::string format_method(const char* method) {
        if (method[0] == '\0') return "unknown";
        std::string result(method, std::min(size_t(8), strlen(method)));
        return result;
    }
    
    // Format data as printable characters
    static std::string format_data(const uint8_t* data, int max_size, int actual_size) {
        std::string result;
        int trunclen = (max_size >= actual_size) ? actual_size : max_size;
        
        for (int i = 0; i < trunclen; ++i) {
            uint8_t c = data[i];
            if (c <= ' ') c = '.';  // Turn control chars into dots
            result += c;
        }
        
        // Suppress trailing spaces
        while (!result.empty() && result.back() == ' ') {
            result.pop_back();
        }
        
        return result;
    }
    
    // Helper function for dates in reports
    static std::string format_seconds_date_time(int64_t sec) {
        if (sec == 0) return "unknown";
        
        time_t tt = sec;
        struct tm* t = localtime(&tt);
        
        char buffer[30];
        sprintf(buffer, "%04d%02d%02d_%02d%02d%02d", 
               t->tm_year + 1900, t->tm_mon + 1, t->tm_mday, 
               t->tm_hour, t->tm_min, t->tm_sec);
        
        return std::string(buffer);
    }
    
    // Convert 10*log2 value to actual byte count
    static int64_t exp_tenths(uint8_t x) {
        int64_t powertwo = x / 10; 
        int64_t fraction = x % 10;
        int64_t retval = 1ll << powertwo;
        retval = retval * kPowerTwoTenths[fraction] + 0.5;
        return retval;
    }
    
    // Estimate RPC message transmission time
    static int64_t rpc_msglen_to_usec(uint8_t lglen, int64_t msg_overhead_bytes = 100) {
        // Assume 110 bytes per usec at 1 Gb/s (with overhead)
        return (exp_tenths(lglen) + msg_overhead_bytes) / 110;
    }
    
    // Get greater of two values
    static int64_t max(int64_t a, int64_t b) {
        return (a >= b) ? a : b;
    }
};

// RPCNanoLogger - Uses NanoLog for high-performance text-based RPC logging
class RPCNanoLogger {
public:
    RPCNanoLogger() : m_ready(false) {}

    // Constructor - initializes NanoLog
    RPCNanoLogger(const std::string& filename) : m_ready(false) {
        open(filename);
    }
    
    // Destructor
    ~RPCNanoLogger() {
        bool was_ready = m_ready.load();
        m_ready = false;
        if (worker_thread.joinable()) {
            worker_thread.join();
        }
        if (was_ready) {
            NanoLog::sync();
        }
    }
    
    // Check if logger is ready
    bool is_ready() const { return m_ready; }

    void open(const std::string_view filename, NanoLog::LogLevel log_level = NanoLog::LogLevel::NOTICE, 
              std::size_t batch_size = 10000, std::size_t timeout_ms = 10) {
        
        // If there's already a worker thread running, stop it first
        if (use_nanolog_background_thread() && worker_thread.joinable()) {
            m_ready = false;  // Signal the existing thread to stop
            worker_thread.join();  // Wait for it to finish
        }
        
        if (std::filesystem::exists(filename)) {
            std::filesystem::remove(filename);
        }
        NanoLog::setLogFile(filename.data());
        NanoLog::preallocate();
        NanoLog::setLogLevel(log_level);
        // NanoLog::sync();
        m_ready = true;

        if (use_nanolog_background_thread()) {
            worker_thread = std::thread([this, batch_size, timeout_ms]() {
#if defined(__linux__) || defined(__unix__)
            pthread_setname_np(pthread_self(), "NanoLogWorker");
#endif
            std::vector<LogEntry> batch_entries;
            batch_entries.resize(batch_size);
            std::size_t index = 0;
            auto start = std::chrono::steady_clock::now();
            
            while (m_ready) {
                if (queue.try_dequeue(batch_entries[index])) {
                    // Process the log entry
                    process_log_entry(batch_entries[index]);
                    index++;
                } else {
                    // Sleep for a bit
                    std::this_thread::sleep_for(std::chrono::nanoseconds(500));
                }
                
                auto end = std::chrono::steady_clock::now();
                auto elapsed = std::chrono::duration_cast<std::chrono::milliseconds>(end - start);
                
                // Flush periodically
                if (index == batch_size || elapsed.count() > static_cast<long>(timeout_ms)) {
                    if (index > 0) {
                        NanoLog::sync();
                        index = 0;
                    }
                    start = end;
                }
            }
            });
        }        
    }

    // Client-side logging
    uint64_t log_client_send(
        uint32_t rpcid,
        uint32_t parent,
        const NetworkAddress& client,
        const NetworkAddress& server,
        std::string_view method,
        const RPCMessage& message
    ) {
        if (!m_ready) return 0;
        
        int64_t timestamp = get_current_usec();
        uint8_t lglen = calculate_ten_lg(message.length);
        
        if (use_nanolog_background_thread()) {
            // Use background thread for better performance
            LogEntry entry;
        entry.type = LogEntryType::ClientSend;
        entry.rpcid = rpcid;
        entry.parent = parent;
        entry.client = client;
        entry.server = server;
        // Copy method name directly without string operations
        size_t method_len = std::min(method.length(), size_t(kMaxMethodNameSize - 1));
        std::memcpy(entry.method, method.data(), method_len);
        entry.method[method_len] = '\0';  // Null terminate
        entry.timestamp = timestamp;
        entry.lglen = lglen;
        entry.message_length = message.length;
        // Copy data directly without string operations
        if (message.data && message.length > 0) {
            size_t copy_len = std::min(message.length, static_cast<uint32_t>(kMaxLogDataSize - 1));
            std::memcpy(entry.data, message.data, copy_len);
            entry.data[copy_len] = '\0';  // Null terminate
        }
        
            queue.enqueue(entry);
        } else {
            // Format addresses and status directly to avoid string allocation
            char client_addr[32], server_addr[32];
            format_address_direct(client, client_addr, sizeof(client_addr));
            format_address_direct(server, server_addr, sizeof(server_addr));
            size_t method_len = std::min(method.length(), size_t(kMaxMethodNameSize));
            const char* data_str = (message.data && message.length > 0) ? 
                reinterpret_cast<const char*>(message.data) : "";
            int data_len = std::min(message.length, static_cast<uint32_t>(kMaxLogDataSize));
            
            NANO_LOG(LogLevel::NOTICE, 
                    "RPC_CLIENT_SEND rpcid=%u parent=%u client=%s server=%s method=%.*s "
                    "timestamp=%" PRId64 " lglen=%u datalength=%u data='%.*s'",
                    rpcid, parent, 
                    client_addr, server_addr, static_cast<int>(method_len), method.data(),
                    timestamp, lglen, message.length, data_len, data_str);
        }
        
        return timestamp;
    }
    
    void log_client_recv(
        uint32_t rpcid,
        uint32_t parent,
        const NetworkAddress& client,
        const NetworkAddress& server,
        std::string_view method,
        RPCStatus status,
        const RPCMessage& message,
        int64_t req_send_time,
        int64_t req_rcv_time,
        int64_t resp_send_time
    ) {
        if (!m_ready) return;
        
        int64_t resp_rcv_time = get_current_usec();
        uint8_t lglen1 = 0; // Request length not available here
        uint8_t lglen2 = calculate_ten_lg(message.length);
        
        if (use_nanolog_background_thread()) {
            LogEntry entry;
            entry.type = LogEntryType::ClientRecv;
            entry.rpcid = rpcid;
            entry.parent = parent;
            entry.client = client;
            entry.server = server;
            // Copy method name directly without string operations
            size_t method_len = std::min(method.length(), size_t(kMaxMethodNameSize - 1));
            std::memcpy(entry.method, method.data(), method_len);
            entry.method[method_len] = '\0';
            entry.status = status;
            entry.req_send_time = req_send_time;
            entry.req_rcv_time = req_rcv_time;
            entry.resp_send_time = resp_send_time;
            entry.resp_rcv_time = resp_rcv_time;
            entry.lglen1 = lglen1;
            entry.lglen2 = lglen2;
            entry.message_length = message.length;
            // Copy data directly without string operations
            if (message.data && message.length > 0) {
                size_t copy_len = std::min(message.length, static_cast<uint32_t>(kMaxLogDataSize - 1));
                std::memcpy(entry.data, message.data, copy_len);
                entry.data[copy_len] = '\0';
            }
        
            queue.enqueue(entry);
        } else {
            // Format addresses and status directly to avoid string allocation
            char client_addr[32], server_addr[32];
            format_address_direct(client, client_addr, sizeof(client_addr));
            format_address_direct(server, server_addr, sizeof(server_addr));
            size_t method_len = std::min(method.length(), size_t(kMaxMethodNameSize));
            const char* status_str = get_status_string_direct(status);
            const char* data_str = (message.data && message.length > 0) ? 
                reinterpret_cast<const char*>(message.data) : "";
            int data_len = std::min(message.length, static_cast<uint32_t>(kMaxLogDataSize));
            
            NANO_LOG(LogLevel::NOTICE,
                    "RPC_CLIENT_RECV rpcid=%u parent=%u client=%s server=%s method=%.*s "
                    "status=%s req_send=%" PRId64 " req_rcv=%" PRId64 " resp_send=%" PRId64 " resp_rcv=%" PRId64 " "
                    "lglen1=%u lglen2=%u datalength=%u data='%.*s'",
                    rpcid, parent, client_addr, server_addr, static_cast<int>(method_len), method.data(),
                    status_str, req_send_time, req_rcv_time, resp_send_time, resp_rcv_time,
                    lglen1, lglen2, message.length, data_len, data_str);
        }
    }
    
    // Server-side logging
    void log_server_recv(
        uint32_t rpcid,
        uint32_t parent,
        const NetworkAddress& client,
        const NetworkAddress& server,
        std::string_view method,
        const RPCMessage& message,
        int64_t req_send_time
    ) {
        if (!m_ready) return;
        
        int64_t req_rcv_time = get_current_usec();
        uint8_t lglen = calculate_ten_lg(message.length);
        
        if (use_nanolog_background_thread()) {
            LogEntry entry;
            entry.type = LogEntryType::ServerRecv;
        entry.rpcid = rpcid;
        entry.parent = parent;
        entry.client = client;
        entry.server = server;
        // Copy method name directly without string operations
        size_t method_len = std::min(method.length(), size_t(kMaxMethodNameSize - 1));
        std::memcpy(entry.method, method.data(), method_len);
        entry.method[method_len] = '\0';
        entry.req_send_time = req_send_time;
        entry.req_rcv_time = req_rcv_time;
        entry.lglen = lglen;
        entry.message_length = message.length;
        // Copy data directly without string operations
        if (message.data && message.length > 0) {
            size_t copy_len = std::min(message.length, static_cast<uint32_t>(kMaxLogDataSize - 1));
            std::memcpy(entry.data, message.data, copy_len);
            entry.data[copy_len] = '\0';
        }
        
            queue.enqueue(entry);
        } else {
            // Format addresses directly to avoid string allocation
            char client_addr[32], server_addr[32];
            format_address_direct(client, client_addr, sizeof(client_addr));
            format_address_direct(server, server_addr, sizeof(server_addr));
            size_t method_len = std::min(method.length(), size_t(kMaxMethodNameSize));
            const char* data_str = (message.data && message.length > 0) ? 
                reinterpret_cast<const char*>(message.data) : "";
            int data_len = std::min(message.length, static_cast<uint32_t>(kMaxLogDataSize));
            
            NANO_LOG(LogLevel::NOTICE,
                    "RPC_SERVER_RECV rpcid=%u parent=%u client=%s server=%s method=%.*s "
                    "req_send=%" PRId64 " req_rcv=%" PRId64 " lglen=%u datalength=%u data='%.*s'",
                    rpcid, parent, client_addr, server_addr, static_cast<int>(method_len), method.data(),
                    req_send_time, req_rcv_time, lglen, message.length, data_len, data_str);
        }
    }

    void log_server_send(
        uint32_t rpcid,
        uint32_t parent,
        const NetworkAddress& client,
        const NetworkAddress& server,
        std::string_view method,
        RPCStatus status,
        const RPCMessage& message,
        int64_t req_send_time,
        int64_t req_rcv_time
    ) {
        if (!m_ready) return;
        
        int64_t resp_send_time = get_current_usec();
        uint8_t lglen = calculate_ten_lg(message.length);
        
        if (use_nanolog_background_thread()) {
            LogEntry entry;
            entry.type = LogEntryType::ServerSend;
        entry.rpcid = rpcid;
        entry.parent = parent;
        entry.client = client;
        entry.server = server;
        // Copy method name directly without string operations
        size_t method_len = std::min(method.length(), size_t(kMaxMethodNameSize - 1));
        std::memcpy(entry.method, method.data(), method_len);
        entry.method[method_len] = '\0';
        entry.status = status;
        entry.req_send_time = req_send_time;
        entry.req_rcv_time = req_rcv_time;
        entry.resp_send_time = resp_send_time;
        entry.lglen = lglen;
        entry.message_length = message.length;
        // Copy data directly without string operations
        if (message.data && message.length > 0) {
            size_t copy_len = std::min(message.length, static_cast<uint32_t>(kMaxLogDataSize - 1));
            std::memcpy(entry.data, message.data, copy_len);
            entry.data[copy_len] = '\0';
        }
        
            queue.enqueue(entry);
        } else {
            // Format addresses and status directly to avoid string allocation
            char client_addr[32], server_addr[32];
            format_address_direct(client, client_addr, sizeof(client_addr));
            format_address_direct(server, server_addr, sizeof(server_addr));
            size_t method_len = std::min(method.length(), size_t(kMaxMethodNameSize));
            const char* status_str = get_status_string_direct(status);
            const char* data_str = (message.data && message.length > 0) ? 
                reinterpret_cast<const char*>(message.data) : "";
            int data_len = std::min(message.length, static_cast<uint32_t>(kMaxLogDataSize));
            
            NANO_LOG(LogLevel::NOTICE,
                    "RPC_SERVER_SEND rpcid=%u parent=%u client=%s server=%s method=%.*s "
                    "status=%s req_send=%" PRId64 " req_rcv=%" PRId64 " resp_send=%" PRId64 " "
                    "lglen=%u datalength=%u data='%.*s'",
                    rpcid, parent, client_addr, server_addr, static_cast<int>(method_len), method.data(),
                    status_str, req_send_time, req_rcv_time, resp_send_time,
                    lglen, message.length, data_len, data_str);
        }
    }
    
    // Generate reports from NanoLog text files
    static bool generate_text_report(const std::string& nanolog_file, const std::string& text_file) {
        // For NanoLog, we need to first decompress the log file
        std::string decompress_cmd = "NanoLogCpp17Decompressor " + nanolog_file + " " + text_file;
        int result = std::system(decompress_cmd.c_str());
        return (result == 0);
    }
    
    static bool generate_json_report(const std::string& nanolog_file, const std::string& json_file, const char* title = "RPC Transactions") {
        // First decompress to a temporary text file
        std::string temp_file = json_file + ".tmp";
        if (!generate_text_report(nanolog_file, temp_file)) {
            return false;
        }
        
        // Parse the text file and convert to JSON format
        std::ifstream in_file(temp_file);
        if (!in_file.is_open()) {
            return false;
        }
        
        std::ofstream out_file(json_file);
        if (!out_file.is_open()) {
            in_file.close();
            return false;
        }
        
        // Write JSON header (simplified version)
        out_file << "{\n";
        out_file << " \"Comment\" : \"V4 flat RPCs from NanoLog\",\n";
        out_file << " \"title\" : \"" << (title ? title : "RPC Transactions") << "\",\n";
        out_file << " \"events\" : [\n";
        
        std::string line;
        bool first_record = true;
        
        while (std::getline(in_file, line)) {
            // Parse NanoLog text format and extract RPC information
            if (line.find("RPC_CLIENT_RECV") != std::string::npos) {
                if (!first_record) {
                    out_file << ",\n";
                }
                // Parse the log line and format as JSON
                // This is a simplified version - full implementation would parse all fields
                out_file << "  [\"" << line << "\"]";
                first_record = false;
            }
        }
        
        if (!first_record) {
            out_file << "\n";
        }
        out_file << "  ]\n}\n";
        
        in_file.close();
        out_file.close();
        
        // Clean up temporary file
        std::remove(temp_file.c_str());
        return true;
    }
    
    // Flush pending log messages
    void sync() {
        if (m_ready) {
            NanoLog::sync();
        }
    }
    
    // Get NanoLog statistics
    std::string get_stats() {
        return NanoLog::getStats();
    }
    
    // Print NanoLog configuration
    void print_config() {
        NanoLog::printConfig();
    }
    
    // Helper to get current time in microseconds
    static int64_t get_current_usec() {
        struct timeval tv;
        gettimeofday(&tv, NULL);
        return (int64_t)tv.tv_sec * 1000000 + tv.tv_usec;
    }
    
    // Helper to calculate 10 * log2(x)
    static uint8_t calculate_ten_lg(uint32_t x) {
        if (x == 0) return 0;
        
        // Calculate floor(log2(x))
        int32_t floorLog2 = 0;
        uint32_t temp = x;
        while (temp > 1) {
            temp >>= 1;
            floorLog2++;
        }
        
        // Calculate 10 * log2(x) - simplified approach
        double exactLog2 = log2(x);
        return static_cast<uint8_t>(exactLog2 * 10.0 + 0.5); // Round to nearest integer
    }

#ifdef KUTRACE_NANOLOG_ENABLE
    static RPCNanoLogger* get() {
        static RPCNanoLogger logger;
        const char* rpc_file = std::getenv("HF3FS_ENABLE_RPC_NANOLOG_FILE");
        if (rpc_file) {
            if (!logger.is_ready()) {
                logger.open(rpc_file);
            }
            return &logger;
        }
        return nullptr;
    }
#endif

private:
    std::atomic<bool> m_ready = false;
    
    // Background thread support structures (always available for runtime switching)
    enum class LogEntryType {
        ClientSend,
        ClientRecv,
        ServerRecv,
        ServerSend
    };
    
    struct LogEntry {
        LogEntryType type;
        uint32_t rpcid;
        uint32_t parent;
        NetworkAddress client;
        NetworkAddress server;
        char method[kMaxMethodNameSize];  // Fixed-size array instead of std::string
        RPCStatus status = RPCStatus::Success;
        int64_t timestamp = 0;
        int64_t req_send_time = 0;
        int64_t req_rcv_time = 0;
        int64_t resp_send_time = 0;
        int64_t resp_rcv_time = 0;
        uint8_t lglen = 0;
        uint8_t lglen1 = 0;
        uint8_t lglen2 = 0;
        uint32_t message_length = 0;
        char data[kMaxLogDataSize];  // Fixed-size array instead of std::string
        
        // Constructor to initialize arrays
        LogEntry() {
            std::memset(method, 0, sizeof(method));
            std::memset(data, 0, sizeof(data));
        }
    };
    
    moodycamel::ConcurrentQueue<LogEntry> queue;
    std::thread worker_thread;
    
    void process_log_entry(const LogEntry& entry) {
        switch (entry.type) {
            case LogEntryType::ClientSend: {
                // Format addresses directly to avoid string allocation
                char client_addr[32], server_addr[32];
                format_address_direct(entry.client, client_addr, sizeof(client_addr));
                format_address_direct(entry.server, server_addr, sizeof(server_addr));
                
                NANO_LOG(LogLevel::NOTICE, 
                        "RPC_CLIENT_SEND rpcid=%u parent=%u client=%s server=%s method=%s "
                        "timestamp=%" PRId64 " lglen=%u datalength=%u data='%s'",
                        entry.rpcid, entry.parent, client_addr, server_addr,
                        entry.method, entry.timestamp, entry.lglen, 
                        entry.message_length, entry.data);
                break;
            }
                
            case LogEntryType::ClientRecv: {
                char client_addr[32], server_addr[32];
                format_address_direct(entry.client, client_addr, sizeof(client_addr));
                format_address_direct(entry.server, server_addr, sizeof(server_addr));
                const char* status_str = get_status_string_direct(entry.status);
                
                NANO_LOG(LogLevel::NOTICE,
                        "RPC_CLIENT_RECV rpcid=%u parent=%u client=%s server=%s method=%s "
                        "status=%s req_send=%" PRId64 " req_rcv=%" PRId64 " resp_send=%" PRId64 " resp_rcv=%" PRId64 " "
                        "lglen1=%u lglen2=%u datalength=%u data='%s'",
                        entry.rpcid, entry.parent, client_addr, server_addr, 
                        entry.method, status_str, entry.req_send_time, entry.req_rcv_time, 
                        entry.resp_send_time, entry.resp_rcv_time, entry.lglen1, entry.lglen2, 
                        entry.message_length, entry.data);
                break;
            }
                
            case LogEntryType::ServerRecv: {
                char client_addr[32], server_addr[32];
                format_address_direct(entry.client, client_addr, sizeof(client_addr));
                format_address_direct(entry.server, server_addr, sizeof(server_addr));
                
                NANO_LOG(LogLevel::NOTICE,
                        "RPC_SERVER_RECV rpcid=%u parent=%u client=%s server=%s method=%s "
                        "req_send=%" PRId64 " req_rcv=%" PRId64 " lglen=%u datalength=%u data='%s'",
                        entry.rpcid, entry.parent, client_addr, server_addr,
                        entry.method, entry.req_send_time, entry.req_rcv_time, 
                        entry.lglen, entry.message_length, entry.data);
                break;
            }
                
            case LogEntryType::ServerSend: {
                char client_addr[32], server_addr[32];
                format_address_direct(entry.client, client_addr, sizeof(client_addr));
                format_address_direct(entry.server, server_addr, sizeof(server_addr));
                const char* status_str = get_status_string_direct(entry.status);
                
                NANO_LOG(LogLevel::NOTICE,
                        "RPC_SERVER_SEND rpcid=%u parent=%u client=%s server=%s method=%s "
                        "status=%s req_send=%" PRId64 " req_rcv=%" PRId64 " resp_send=%" PRId64 " "
                        "lglen=%u datalength=%u data='%s'",
                        entry.rpcid, entry.parent, client_addr, server_addr,
                        entry.method, status_str, entry.req_send_time, entry.req_rcv_time, 
                        entry.resp_send_time, entry.lglen, entry.message_length, entry.data);
                break;
            }
        }
    }
    
    // Pre-computed status strings for better performance
    static constexpr const char* status_strings[] = {
        "Success",
        "Fail", 
        "TooBusy"
    };
    
    // Direct formatting for NanoLog - no string allocation
    static void format_address_direct(const NetworkAddress& addr, char* buffer, size_t buffer_size) {
        struct in_addr in_addr_obj;
        in_addr_obj.s_addr = addr.ip;
        snprintf(buffer, buffer_size, "%s:%u", inet_ntoa(in_addr_obj), addr.port);
    }

    // Direct status string lookup for NanoLog - no string allocation
    static const char* get_status_string_direct(RPCStatus status) {
        uint32_t status_val = static_cast<uint32_t>(status);
        if (status_val < 3) {
            return status_strings[status_val];
        }
        return "Status "; // Fallback
    }
};

// Macro for generic logging that works with NanoLog's compile-time requirements
#ifdef KUTRACE_NANOLOG_ENABLE
#define KUTRACE_NANOLOG(format, ...) \
    do { \
        auto* logger = kutrace::RPCNanoLogger::get(); \
        if (logger && logger->is_ready()) { \
            NANO_LOG(LogLevel::NOTICE, format, ##__VA_ARGS__); \
        } \
    } while(0)
#else
#define KUTRACE_NANOLOG(format, ...) do {} while(0)
#endif

}

#ifdef KUTRACE_RPC_ENABLE

// For GCC with strict warnings
#define KUTRACE_FOLLY_MARKER_IMPL(label) \
  kutrace::mark_e(label); \
  auto guard_kutrace_##__LINE__ = folly::makeGuard([&] { \
      kutrace::mark_e(fmt::format("/{}", label)); \
  });

#define KUTRACE_FOLLY_MARKER_IMPL_ARG(label, arg) \
  kutrace::mark_e(label, arg); \
  auto guard_kutrace_##__LINE__ = folly::makeGuard([&] { \
      kutrace::mark_e(fmt::format("/{}", label), arg); \
  });

// Choose the right implementation based on argument count
#define GET_MACRO(_1, _2, NAME, ...) NAME

#define KUTRACE_FOLLY_MARKER(...) \
  GET_MACRO(__VA_ARGS__, KUTRACE_FOLLY_MARKER_IMPL_ARG, KUTRACE_FOLLY_MARKER_IMPL)(__VA_ARGS__)

#define KUTRACE_FOLLY_MARKER_RPC_NUM(label) \
    if (KUTraceRPCInfo::get()) { \
        auto rpcid = KUTraceRPCInfo::get()->rpc_id; \
        KUTRACE_FOLLY_MARKER_IMPL_ARG(label, rpcid); \
    } else { \
        KUTRACE_FOLLY_MARKER_IMPL(label); \
    }

#define KUTRACE_FOLLY_MARKER_RPC_NUM_ARG(label, arg) \
    KUTRACE_FOLLY_MARKER_IMPL_ARG(label, arg);

#else
#define KUTRACE_FOLLY_MARKER_RPC_NUM(label)

#define KUTRACE_FOLLY_MARKER_RPC_NUM_ARG(label, arg)

#endif


#include <folly/io/async/Request.h>
#include <atomic>
#include <string>

class KUTraceRPCInfo : public folly::RequestData {
public:
  static constexpr const char* k_token_name = "KUTraceRPCinfo";
  
  static folly::RequestToken const& token() {
    static folly::RequestToken const token(k_token_name);
    return token;
  }

  static inline KUTraceRPCInfo* get() {
    auto rpcinfo = folly::RequestContext::get()->getContextData(token());
    if (!rpcinfo) {
        return nullptr;
    }
    return reinterpret_cast<KUTraceRPCInfo*>(rpcinfo);
  }

  // Required override from folly::RequestData
  bool hasCallback() override { return false; }

  // Constructor
  KUTraceRPCInfo(uint64_t rpc_id_, std::string operation_type_)
    : rpc_id(rpc_id_), operation_type(std::move(operation_type_)) {
        last_rpc_id = rpc_id;
        last_operation_type = operation_type;
    }

  // Helper to set this RPC info in the current request context
  static auto set(uint64_t rpc_id_, std::string_view operation_type_) {
    return folly::ShallowCopyRequestContextScopeGuard(
      KUTraceRPCInfo::token(), 
      std::make_unique<KUTraceRPCInfo>(rpc_id_, std::string(operation_type_))
    );
  }

  // New method that increments a counter with relaxed memory ordering
  static auto set_with_next_rpc_id(std::string_view operation_type_) {
    uint64_t rpc_id_ = next_rpc_id.fetch_add(1, std::memory_order_relaxed);
    
    return folly::ShallowCopyRequestContextScopeGuard(
      KUTraceRPCInfo::token(), 
      std::make_unique<KUTraceRPCInfo>(rpc_id_, std::string(operation_type_))
    );
  }

  static auto set_with_cached_rpc_id(std::string_view operation_type_ = "") {
    if (operation_type_.empty()) {
        operation_type_ = last_operation_type;
    }
    
    return folly::ShallowCopyRequestContextScopeGuard(
      KUTraceRPCInfo::token(), 
      std::make_unique<KUTraceRPCInfo>(last_rpc_id, std::string(operation_type_))
    );
  }

  // Description method
  std::string describe() const { 
    return "RPC ID: " + std::to_string(rpc_id) + ", Type: " + operation_type; 
  }

public:
  uint64_t rpc_id;
  std::string operation_type;
  static inline std::atomic<uint64_t> next_rpc_id = 0;
  static inline std::string last_operation_type;
  static inline uint64_t last_rpc_id = 0;
};
