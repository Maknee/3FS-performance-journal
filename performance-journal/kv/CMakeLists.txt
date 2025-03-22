cmake_minimum_required(VERSION 3.13)
project(3fs_benchmark VERSION 1.0.0 LANGUAGES CXX)

# Set C++ standard
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

# Set RPATH settings for runtime library resolution
set(CMAKE_SKIP_BUILD_RPATH FALSE)
set(CMAKE_BUILD_WITH_INSTALL_RPATH FALSE)
set(CMAKE_INSTALL_RPATH "${CMAKE_INSTALL_PREFIX}/lib")
set(CMAKE_INSTALL_RPATH_USE_LINK_PATH TRUE)

# Set compiler flags
if(CMAKE_CXX_COMPILER_ID MATCHES "GNU|Clang")
    # Standard optimization and warning flags
    set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} -Wall -Wextra -O2")

    # Add profiling options
    option(ENABLE_GPROF "Enable gprof profiling with -pg flag" OFF)
    option(ENABLE_INSTRUMENT_FUNCTIONS "Enable function instrumentation with -finstrument-functions" OFF)

    if(ENABLE_GPROF)
        set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} -pg")
        set(CMAKE_EXE_LINKER_FLAGS "${CMAKE_EXE_LINKER_FLAGS} -pg")
        message(STATUS "Building with gprof profiling support (-pg)")
    endif()

    if(ENABLE_INSTRUMENT_FUNCTIONS)
        set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} -finstrument-functions")
        message(STATUS "Building with function instrumentation (-finstrument-functions)")
    endif()
endif()

# Include directories
include_directories(${CMAKE_CURRENT_SOURCE_DIR}/include)
include_directories(SYSTEM ${LIBURING_INCLUDE_DIR})
include_directories(${CMAKE_CURRENT_SOURCE_DIR}/kutrace_userlib)

# Fetch dependencies
include(FetchContent)

# Fetch nlohmann/json
FetchContent_Declare(
    json
    GIT_REPOSITORY https://github.com/nlohmann/json.git
    GIT_TAG v3.11.2
)
FetchContent_MakeAvailable(json)

# Fetch cxxopts
FetchContent_Declare(
    cxxopts
    GIT_REPOSITORY https://github.com/jarro2783/cxxopts.git
    GIT_TAG v3.1.1
)
FetchContent_MakeAvailable(cxxopts)

# Fetch moodycamel ConcurrentQueue
FetchContent_Declare(
    concurrentqueue
    GIT_REPOSITORY https://github.com/cameron314/concurrentqueue.git
    GIT_TAG v1.0.4
)
FetchContent_MakeAvailable(concurrentqueue)

# Fetch liburing
FetchContent_Declare(
    liburing
    GIT_REPOSITORY https://github.com/axboe/liburing.git
    GIT_TAG liburing-2.5
    CONFIGURE_COMMAND ./configure
    BUILD_COMMAND make
)

# Fetch fmt
FetchContent_Declare(
    fmt
    GIT_REPOSITORY https://github.com/fmtlib/fmt.git
    GIT_TAG 10.2.0 # Use a recent stable version
)
FetchContent_MakeAvailable(fmt)

# Handle liburing manually since it doesn't use CMake
FetchContent_GetProperties(liburing)
if(NOT liburing_POPULATED)
    FetchContent_Populate(liburing)
    execute_process(
        COMMAND ./configure
        WORKING_DIRECTORY ${liburing_SOURCE_DIR}
    )
    execute_process(
        COMMAND make
        WORKING_DIRECTORY ${liburing_SOURCE_DIR}
    )
    set(LIBURING_INCLUDE_DIR ${liburing_SOURCE_DIR}/src/include)
    set(LIBURING_LIBRARY ${liburing_SOURCE_DIR}/src/liburing.a)
endif()

# Check for HF3FS API shared library
set(HF3FS_LIB_PATH "${CMAKE_CURRENT_SOURCE_DIR}/libhf3fs_api_shared.so")
if(NOT EXISTS ${HF3FS_LIB_PATH})
    message(FATAL_ERROR "libhf3fs_api_shared.so not found. Please copy it to ${CMAKE_CURRENT_SOURCE_DIR}")
endif()

# Add current directory to link directories to find libhf3fs_api_shared.so
link_directories(${CMAKE_CURRENT_SOURCE_DIR}/)

# Create a custom command to copy the shared library to the build directory
add_custom_command(
    OUTPUT ${CMAKE_BINARY_DIR}/libhf3fs_api_shared.so
    COMMAND ${CMAKE_COMMAND} -E copy
            ${HF3FS_LIB_PATH}
            ${CMAKE_BINARY_DIR}/libhf3fs_api_shared.so
    DEPENDS ${HF3FS_LIB_PATH}
    COMMENT "Copying libhf3fs_api_shared.so to build directory"
)

# Custom target for copying shared library
add_custom_target(copy_hf3fs_lib ALL
    DEPENDS ${CMAKE_BINARY_DIR}/libhf3fs_api_shared.so
)

# Copy moodycamel ConcurrentQueue header to include directory
FetchContent_GetProperties(concurrentqueue)
file(COPY ${concurrentqueue_SOURCE_DIR}/concurrentqueue.h
     DESTINATION ${CMAKE_CURRENT_SOURCE_DIR}/include)
file(COPY ${concurrentqueue_SOURCE_DIR}/lightweightsemaphore.h
     DESTINATION ${CMAKE_CURRENT_SOURCE_DIR}/include)
file(COPY ${concurrentqueue_SOURCE_DIR}/blockingconcurrentqueue.h
     DESTINATION ${CMAKE_CURRENT_SOURCE_DIR}/include)

# Main executable
add_executable(3fs_benchmark src/3fs_benchmark.cpp)
add_dependencies(3fs_benchmark copy_hf3fs_lib)

# Link libraries
target_link_libraries(3fs_benchmark PRIVATE
    nlohmann_json::nlohmann_json
    cxxopts
    hf3fs_api_shared
    fmt::fmt # Added fmt here
)

# Link liburing
target_link_libraries(3fs_benchmark PRIVATE ${LIBURING_LIBRARY})
target_compile_definitions(3fs_benchmark PRIVATE HAVE_LIBURING=1)

# Include moodycamel header paths
target_include_directories(3fs_benchmark PRIVATE ${concurrentqueue_SOURCE_DIR})

# Install targets
install(TARGETS 3fs_benchmark DESTINATION bin)
install(FILES ${HF3FS_LIB_PATH} DESTINATION lib)

# Create directories
file(MAKE_DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR}/src)
file(MAKE_DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR}/include)