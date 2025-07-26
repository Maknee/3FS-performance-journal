# Benchmark CMakeLists.txt

# Create the benchmark executable
add_executable(kutrace_benchmark
    main.cpp
    benchmark_runner.cpp
)

# Link against the kutrace logger and required libraries
target_link_libraries(kutrace_benchmark PRIVATE 
    kutrace_logger_simple
    Threads::Threads
)

# Link with NanoLog if available
if(TARGET NanoLog::NanoLog)
    target_link_libraries(kutrace_benchmark PRIVATE NanoLog::NanoLog)
endif()

# Set target properties
set_target_properties(kutrace_benchmark PROPERTIES
    CXX_STANDARD 20
    CXX_STANDARD_REQUIRED ON
    OUTPUT_NAME "kutrace_benchmark"
)

# Add compile definitions for the benchmark
target_compile_definitions(kutrace_benchmark PRIVATE
    -DKUTRACE_RPC_ENABLE
    -DKUTRACE_NANOLOG_ENABLE
)

# Include directories for benchmark
target_include_directories(kutrace_benchmark PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}
    ${CMAKE_CURRENT_SOURCE_DIR}/../include
    ${CMAKE_CURRENT_SOURCE_DIR}/../third_party
    ${CMAKE_CURRENT_SOURCE_DIR}/../third_party/concurrentqueue
)

# Compiler-specific options
if(CMAKE_CXX_COMPILER_ID STREQUAL "GNU" OR CMAKE_CXX_COMPILER_ID STREQUAL "Clang")
    target_compile_options(kutrace_benchmark PRIVATE
        -pthread
        -fno-omit-frame-pointer
    )
    
    # Add optimization flags for Release builds
    if(CMAKE_BUILD_TYPE STREQUAL "Release")
        target_compile_options(kutrace_benchmark PRIVATE
            -march=native
            -mtune=native
        )
    endif()
endif()

# Installation
install(TARGETS kutrace_benchmark
    RUNTIME DESTINATION bin
)

# Custom target for running benchmarks
add_custom_target(run_benchmark
    COMMAND kutrace_benchmark --help
    DEPENDS kutrace_benchmark
    COMMENT "Show benchmark help"
)

add_custom_target(run_quick_benchmark
    COMMAND kutrace_benchmark -t 1 -n 1000 -d ./quick_bench_results -v
    DEPENDS kutrace_benchmark
    COMMENT "Run quick benchmark test"
    WORKING_DIRECTORY ${CMAKE_BINARY_DIR}
)

add_custom_target(run_full_benchmark
    COMMAND kutrace_benchmark -t 4 -n 10000 -d ./full_bench_results -v
    DEPENDS kutrace_benchmark
    COMMENT "Run full benchmark test"
    WORKING_DIRECTORY ${CMAKE_BINARY_DIR}
) 