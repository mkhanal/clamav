# Copyright (C) 2019-2025 Cisco Systems, Inc. and/or its affiliates. All rights reserved.

if(WIN32)
    add_definitions(-DWIN32_LEAN_AND_MEAN)

    # Windows compatibility headers
    include_directories(${CMAKE_SOURCE_DIR}/win32/compat)
endif()

# Move public headers to a dedicated INTERFACE library
#
# An interface is required because libclamav objects will depend on the
# interface to put unrar_iface.h in the include path, but we don't want to link
# with it.
# libclamunrar_iface will be dynamically loaded at run time, if enabled.
add_library(clamunrar_iface_iface INTERFACE)
target_sources(clamunrar_iface_iface
    INTERFACE
        unrar_iface.h )
target_include_directories( clamunrar_iface_iface
    INTERFACE
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}> )

add_library( ClamAV::libunrar_iface_iface ALIAS clamunrar_iface_iface )

if(ENABLE_UNRAR AND ENABLE_UNRAR_LIBARCHIVE)
    # Build the vendored libarchive as a static library with no optional
    # dependencies, so the RAR readers add nothing to the runtime.
    # It is built by its own CMake project (ExternalProject) so its options
    # and configure checks stay out of ClamAV's cache.
    include(ExternalProject)

    get_property(_multi_config GLOBAL PROPERTY GENERATOR_IS_MULTI_CONFIG)

    set(LIBARCHIVE_SOURCE_DIR ${CMAKE_SOURCE_DIR}/libclamarchive)
    set(LIBARCHIVE_BINARY_DIR ${CMAKE_CURRENT_BINARY_DIR}/libarchive-build)
    set(LIBARCHIVE_LIB_DIR    ${CMAKE_CURRENT_BINARY_DIR}/libarchive-lib)
    if(MSVC)
        set(LIBARCHIVE_STATIC_LIB ${LIBARCHIVE_LIB_DIR}/archive_static.lib)
    else()
        set(LIBARCHIVE_STATIC_LIB ${LIBARCHIVE_LIB_DIR}/libarchive.a)
    endif()

    set(LIBARCHIVE_CMAKE_ARGS
        -DCMAKE_C_COMPILER=${CMAKE_C_COMPILER}
        -DCMAKE_C_FLAGS=${CMAKE_C_FLAGS}
        -DCMAKE_POSITION_INDEPENDENT_CODE=ON
        -DCMAKE_ARCHIVE_OUTPUT_DIRECTORY=${LIBARCHIVE_LIB_DIR}
        -DCMAKE_ARCHIVE_OUTPUT_DIRECTORY_DEBUG=${LIBARCHIVE_LIB_DIR}
        -DCMAKE_ARCHIVE_OUTPUT_DIRECTORY_RELEASE=${LIBARCHIVE_LIB_DIR}
        -DCMAKE_ARCHIVE_OUTPUT_DIRECTORY_RELWITHDEBINFO=${LIBARCHIVE_LIB_DIR}
        -DCMAKE_ARCHIVE_OUTPUT_DIRECTORY_MINSIZEREL=${LIBARCHIVE_LIB_DIR}
        -DBUILD_SHARED_LIBS=OFF
        -DENABLE_INSTALL=OFF
        -DENABLE_TEST=OFF
        -DENABLE_WERROR=OFF
        -DENABLE_TAR=OFF
        -DENABLE_CPIO=OFF
        -DENABLE_CAT=OFF
        -DENABLE_UNZIP=OFF
        -DENABLE_MBEDTLS=OFF
        -DENABLE_NETTLE=OFF
        -DENABLE_OPENSSL=OFF
        -DENABLE_CNG=OFF
        -DENABLE_MD=OFF
        -DENABLE_LIBB2=OFF
        -DENABLE_LZ4=OFF
        -DENABLE_LZO=OFF
        -DENABLE_LZMA=OFF
        -DENABLE_ZSTD=OFF
        -DENABLE_ZLIB=OFF
        -DENABLE_BZip2=OFF
        -DENABLE_LIBXML2=OFF
        -DENABLE_BSDXML=OFF
        -DENABLE_EXPAT=OFF
        -DENABLE_WIN32_XMLLITE=OFF
        -DENABLE_PCREPOSIX=OFF
        -DENABLE_PCRE2POSIX=OFF
        -DENABLE_LIBGCC=OFF
        -DENABLE_XATTR=OFF
        -DENABLE_ACL=OFF
        -DENABLE_ICONV=OFF)
    if(WIN32)
        list(APPEND LIBARCHIVE_CMAKE_ARGS -DPOSIX_REGEX_LIB=NONE)
    endif()
    if(NOT _multi_config)
        list(APPEND LIBARCHIVE_CMAKE_ARGS -DCMAKE_BUILD_TYPE=${CMAKE_BUILD_TYPE})
    endif()
    foreach(_var CMAKE_TOOLCHAIN_FILE CMAKE_SYSROOT CMAKE_OSX_ARCHITECTURES CMAKE_OSX_DEPLOYMENT_TARGET CMAKE_OSX_SYSROOT CMAKE_MSVC_RUNTIME_LIBRARY CMAKE_C_COMPILER_TARGET)
        if(DEFINED ${_var})
            list(APPEND LIBARCHIVE_CMAKE_ARGS "-D${_var}=${${_var}}")
        endif()
    endforeach()

    ExternalProject_Add(libarchive_external
        SOURCE_DIR       ${LIBARCHIVE_SOURCE_DIR}
        BINARY_DIR       ${LIBARCHIVE_BINARY_DIR}
        CMAKE_ARGS       ${LIBARCHIVE_CMAKE_ARGS}
        BUILD_COMMAND    ${CMAKE_COMMAND} --build <BINARY_DIR> --target archive_static --config $<CONFIG>
        INSTALL_COMMAND  ""
        BUILD_BYPRODUCTS ${LIBARCHIVE_STATIC_LIB}
        BUILD_ALWAYS     ON)

    add_library(clamav_libarchive_static STATIC IMPORTED GLOBAL)
    set_target_properties(clamav_libarchive_static PROPERTIES
        IMPORTED_LOCATION             ${LIBARCHIVE_STATIC_LIB}
        INTERFACE_INCLUDE_DIRECTORIES ${LIBARCHIVE_SOURCE_DIR}/libarchive
        INTERFACE_COMPILE_DEFINITIONS LIBARCHIVE_STATIC)
    add_dependencies(clamav_libarchive_static libarchive_external)
    if(WIN32)
        set_property(TARGET clamav_libarchive_static APPEND PROPERTY INTERFACE_LINK_LIBRARIES bcrypt)
    endif()

    set(UNRAR_IFACE_SOURCES
        unrar_iface_libarchive.c
        unrar_iface.h
    )
    set(UNRAR_IFACE_BACKEND_INCLUDE_DIRS "")
    set(UNRAR_IFACE_BACKEND_SHARED clamav_libarchive_static)
    set(UNRAR_IFACE_BACKEND_STATIC clamav_libarchive_static)
    set(UNRAR_IFACE_COMPILE_FLAGS  "${WARNCFLAGS}")
elseif(ENABLE_UNRAR)
    set(UNRAR_IFACE_SOURCES
        unrar_iface.cpp
        unrar_iface.h
    )
    set(UNRAR_IFACE_BACKEND_INCLUDE_DIRS $<TARGET_PROPERTY:ClamAV::libunrar,INTERFACE_INCLUDE_DIRECTORIES>)
    set(UNRAR_IFACE_BACKEND_SHARED ClamAV::libunrar)
    set(UNRAR_IFACE_BACKEND_STATIC ClamAV::libunrar_static)
    set(UNRAR_IFACE_COMPILE_FLAGS  "${WARNCXXFLAGS} ${CXX1XCXXFLAGS}")
endif()

if(ENABLE_UNRAR)
    # not using an object library for the sake of Xcode compatibility
    # See: https://cmake.org/pipermail/cmake/2016-May/063479.html

    if(ENABLE_SHARED_LIB)
        # The clamunrar_iface SHARED library.
        add_library( clamunrar_iface SHARED )
        set_target_properties( clamunrar_iface PROPERTIES
            VERSION ${LIBCLAMAV_VERSION}
            SOVERSION ${LIBCLAMAV_SOVERSION}
            CXX_STANDARD 11
        )

        target_sources( clamunrar_iface
            PRIVATE
                ${UNRAR_IFACE_SOURCES}
            PUBLIC
                ${CMAKE_CURRENT_SOURCE_DIR}/unrar_iface.h )

        target_include_directories( clamunrar_iface
            PRIVATE
                ${CMAKE_BINARY_DIR} # For clamav-config.h
                ${UNRAR_IFACE_BACKEND_INCLUDE_DIRS}
                $<TARGET_PROPERTY:ClamAV::libclamav,INTERFACE_INCLUDE_DIRECTORIES> )

        set_target_properties( clamunrar_iface PROPERTIES
            COMPILE_FLAGS "${UNRAR_IFACE_COMPILE_FLAGS}" )

        if (APPLE AND CLAMAV_SIGN_FILE)
            set_target_properties( clamunrar_iface PROPERTIES
                XCODE_ATTRIBUTE_CODE_SIGN_IDENTITY ${CODE_SIGN_IDENTITY}
                XCODE_ATTRIBUTE_DEVELOPMENT_TEAM ${DEVELOPMENT_TEAM_ID}
            )
        endif()

        if(WIN32)
            set_target_properties(clamunrar_iface PROPERTIES WINDOWS_EXPORT_ALL_SYMBOLS ON)
        elseif(UNIX AND NOT APPLE AND NOT AIX)
            target_link_options(clamunrar_iface PRIVATE "-Wl,--version-script=${CMAKE_CURRENT_SOURCE_DIR}/libclamunrar_iface.map")
            if (${CMAKE_SYSTEM_NAME} MATCHES "SunOS")
                # Solaris 11.4 linker supports a subset of GNU ld version scripts, but requires a special option to enable
                target_link_options(clamunrar_iface PRIVATE "-Wl,-z,gnu-version-script-compat")
            endif()
        endif()

        # Private (internal-only) dependencies.
        target_link_libraries( clamunrar_iface
            PRIVATE
                ${UNRAR_IFACE_BACKEND_SHARED}
            PUBLIC
                ClamAV::libunrar_iface_iface)

        if(WIN32)
            install(TARGETS clamunrar_iface DESTINATION . COMPONENT libraries)
            install( FILES $<TARGET_PDB_FILE:clamunrar_iface> DESTINATION . OPTIONAL COMPONENT libraries )
        else()
            install(TARGETS clamunrar_iface DESTINATION ${CMAKE_INSTALL_LIBDIR} COMPONENT libraries)
        endif()

        add_library( ClamAV::libunrar_iface ALIAS clamunrar_iface )
    endif()

    if(ENABLE_STATIC_LIB)
        # The clamunrar_iface static library.
        add_library( clamunrar_iface_static STATIC)
        set_target_properties( clamunrar_iface_static PROPERTIES
            CXX_STANDARD 11
        )

        target_sources( clamunrar_iface_static
            PRIVATE
                ${UNRAR_IFACE_SOURCES}
            PUBLIC
                ${CMAKE_CURRENT_SOURCE_DIR}/unrar_iface.h )

        target_include_directories( clamunrar_iface_static
            PRIVATE
                ${CMAKE_BINARY_DIR} # For clamav-config.h
                ${UNRAR_IFACE_BACKEND_INCLUDE_DIRS}
                $<TARGET_PROPERTY:ClamAV::libclamav,INTERFACE_INCLUDE_DIRECTORIES> )

        # Public (forwarded) dependencies.
        target_link_libraries( clamunrar_iface_static
            PRIVATE
                ${UNRAR_IFACE_BACKEND_STATIC} )

        if(WIN32)
            install(TARGETS clamunrar_iface_static DESTINATION . COMPONENT libraries)
        else()
            install(TARGETS clamunrar_iface_static DESTINATION ${CMAKE_INSTALL_LIBDIR} COMPONENT libraries)
        endif()

        add_library( ClamAV::libunrar_iface_static ALIAS clamunrar_iface_static )
        if(NOT ENABLE_SHARED_LIB)
            add_library( ClamAV::libunrar_iface ALIAS clamunrar_iface_static )
        endif()
    endif()
endif()
