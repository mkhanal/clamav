#
# libclamav features written in Rust
#
# Copyright (C) 2021-2025 Cisco Systems, Inc. and/or its affiliates. All rights reserved.
#

# The Rust openssl-sys crate needs to know how to find the OpenSSL headers and libraries.
get_filename_component(OPENSSL_DIR "${OPENSSL_INCLUDE_DIR}" DIRECTORY)

set(OPENSSL_LIBS "")

# Get the libcrypto library.
# Remove path and extension.
get_filename_component(LIBNAME "${OPENSSL_CRYPTO_LIBRARY}" NAME_WLE)
# Remove "lib" prefix, if present.
string(REGEX REPLACE "^lib" "" LIBNAME "${LIBNAME}")
# Add libcrypto.
set(OPENSSL_LIBS "${LIBNAME}")

# Get the libssl library.
# Remove path and extension.
get_filename_component(LIBNAME "${OPENSSL_SSL_LIBRARY}" NAME_WLE)
# Remove "lib" prefix, if present.
string(REGEX REPLACE "^lib" "" LIBNAME "${LIBNAME}")
# Add libssl.
set(OPENSSL_LIBS "${OPENSSL_LIBS}:${LIBNAME}")

# Get directory of the first library to use for the OPENSSL_LIB_DIR.
set(OPENSSL_CRYPTO_LIBRARY_FILE "${OPENSSL_CRYPTO_LIBRARY}")
list(FIND OPENSSL_CRYPTO_LIBRARY_FILE "optimized" OPENSSL_OPTIMIZED_INDEX)
if(NOT OPENSSL_OPTIMIZED_INDEX EQUAL -1)
    # A per-configuration library list ("optimized;<file>;debug;<file>"): use the release file.
    math(EXPR OPENSSL_OPTIMIZED_INDEX "${OPENSSL_OPTIMIZED_INDEX} + 1")
    list(GET OPENSSL_CRYPTO_LIBRARY_FILE ${OPENSSL_OPTIMIZED_INDEX} OPENSSL_CRYPTO_LIBRARY_FILE)
endif()
get_filename_component(OPENSSL_LIB_DIR "${OPENSSL_CRYPTO_LIBRARY_FILE}" DIRECTORY)

set(ENVIRONMENT "")
list(APPEND ENVIRONMENT "OPENSSL_DIR=${OPENSSL_DIR}")
list(APPEND ENVIRONMENT "OPENSSL_INCLUDE_DIR=${OPENSSL_INCLUDE_DIR}")
if(NOT MSVC)
    # Setting OPENSSL_LIBS caused failures in testing for Windows.
    # It's possible they require a different format or the .lib or .dll extensions.
    # For now, we'll only set this for non-Windows builds.
    list(APPEND ENVIRONMENT "OPENSSL_LIBS=${OPENSSL_LIBS}")
endif()
list(APPEND ENVIRONMENT "OPENSSL_LIB_DIR=${OPENSSL_LIB_DIR}")

# libclamav rust static library
add_rust_library(TARGET clamav_rust
    SOURCE_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}"
    BINARY_DIRECTORY "${CMAKE_BINARY_DIR}"
    ENVIRONMENT "${ENVIRONMENT}"
    INCLUDE_DIRECTORIES "$<TARGET_PROPERTY:ClamAV::libclamav,INCLUDE_DIRECTORIES>"
    # Tests cannot be pre-compiled here, because there are circular dependencies
    # between libclamav_rust and libclamav to include calls like `cli_getdsig()`
    # as well as the logging functions.
    PRECOMPILE_TESTS FALSE
)
if (WIN32)
    target_link_libraries(clamav_rust PUBLIC INTERFACE Userenv)
endif()

if(WIN32)
    install(FILES $<TARGET_FILE:clamav_rust> DESTINATION . COMPONENT libraries)
else()
    install(FILES $<TARGET_FILE:clamav_rust> DESTINATION ${CMAKE_INSTALL_LIBDIR} COMPONENT libraries)
endif()

add_library(ClamAV::libclamav_rust ALIAS clamav_rust)
