cmake_minimum_required(VERSION 3.16)
project(kutrace_rpc_logger VERSION 1.0.0 LANGUAGES CXX)

# Set C++ standard
set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

# Set build type default
if(NOT CMAKE_BUILD_TYPE)
    set(CMAKE_BUILD_TYPE Release)
endif()

# Compiler flags
set(CMAKE_CXX_FLAGS "-Wall -Wextra")
set(CMAKE_CXX_FLAGS_DEBUG "-g -O0 -DDEBUG")
set(CMAKE_CXX_FLAGS_RELEASE "-O3 -DNDEBUG")

# Find required packages
find_package(Threads REQUIRED)

# Add include directories
include_directories(src/include)
include_directories(src/third_party)
include_directories(src/third_party/concurrentqueue)

# Check for optional dependencies
find_package(PkgConfig QUIET)
if(PkgConfig_FOUND)
    pkg_check_modules(FOLLY QUIET folly)
    if(FOLLY_FOUND)
        add_definitions(-DHAVE_FOLLY)
        include_directories(${FOLLY_INCLUDE_DIRS})
        link_directories(${FOLLY_LIBRARY_DIRS})
    else()
        message(WARNING "Folly not found. Some features may be disabled.")
    endif()
else()
    message(WARNING "PkgConfig not found. Cannot check for Folly.")
endif()

# Try to find NanoLog from the main project
find_package(NanoLog QUIET)
if(NOT NanoLog_FOUND)
    # If not found, try to use FetchContent to get it
    include(FetchContent)
    FetchContent_Declare(
        nanolog
        GIT_REPOSITORY https://github.com/Maknee/NanoLog.git
        GIT_TAG master
        GIT_SUBMODULES_RECURSE YES
    )
    set(BUILD_TESTING OFF CACHE BOOL "Disable NanoLog tests" FORCE)
    set(BUILD_DECOMPRESSOR ON CACHE BOOL "Build NanoLog decompressor" FORCE)
    FetchContent_MakeAvailable(nanolog)
endif()

# Create header-only library for kutrace_logger
add_library(kutrace_logger INTERFACE)
target_include_directories(kutrace_logger INTERFACE
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/src/include>
    $<INSTALL_INTERFACE:include>
)
target_compile_features(kutrace_logger INTERFACE cxx_std_20)

# Link with NanoLog
if(TARGET NanoLog::NanoLog)
    target_link_libraries(kutrace_logger INTERFACE NanoLog::NanoLog)
else()
    message(WARNING "NanoLog target not found. Some functionality may be limited.")
endif()

# Create a simplified version without Folly dependencies for testing
add_library(kutrace_logger_simple INTERFACE)
target_include_directories(kutrace_logger_simple INTERFACE
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/src/include>
    $<INSTALL_INTERFACE:include>
)
target_compile_features(kutrace_logger_simple INTERFACE cxx_std_20)
target_compile_definitions(kutrace_logger_simple INTERFACE 
    -DKUTRACE_NO_FOLLY
    -DKUTRACE_RPC_ENABLE
    -DKUTRACE_NANOLOG_ENABLE
)

# Link simplified version with NanoLog too
if(TARGET NanoLog::NanoLog)
    target_link_libraries(kutrace_logger_simple INTERFACE NanoLog::NanoLog)
endif()

# Download concurrentqueue
if(NOT EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/src/third_party/concurrentqueue/concurrentqueue.h")
    message(STATUS "Downloading concurrentqueue...")
    file(DOWNLOAD
        "https://raw.githubusercontent.com/cameron314/concurrentqueue/refs/heads/master/concurrentqueue.h"
        "${CMAKE_CURRENT_SOURCE_DIR}/src/third_party/concurrentqueue/concurrentqueue.h"
        SHOW_PROGRESS
    )
endif()

# Add subdirectories
add_subdirectory(src/benchmark)

# Installation
install(TARGETS kutrace_logger
    EXPORT kutrace_logger_targets
    LIBRARY DESTINATION lib
    ARCHIVE DESTINATION lib
    RUNTIME DESTINATION bin
    INCLUDES DESTINATION include
)

install(FILES 
    src/include/kutrace_logger.h
    DESTINATION include
)

install(EXPORT kutrace_logger_targets
    FILE kutrace_logger_targets.cmake
    NAMESPACE kutrace::
    DESTINATION lib/cmake/kutrace_logger
)

# Package config (simplified for now)
# TODO: Add proper package config files for find_package support

# Print configuration summary
message(STATUS "")
message(STATUS "Configuration Summary:")
message(STATUS "  Build type: ${CMAKE_BUILD_TYPE}")
message(STATUS "  C++ standard: ${CMAKE_CXX_STANDARD}")
message(STATUS "  Install prefix: ${CMAKE_INSTALL_PREFIX}")
if(FOLLY_FOUND)
    message(STATUS "  Folly support: Yes")
else()
    message(STATUS "  Folly support: No")
endif()
if(TARGET NanoLog::NanoLog)
    message(STATUS "  NanoLog support: Yes")
else()
    message(STATUS "  NanoLog support: No")
endif()
message(STATUS "") 