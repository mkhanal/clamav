FROM rust:1.99.1-trixie@sha256:09027f873d45b8ecd1dc86f1fa13b7a62b875c961f017a0e331267b350430137 AS build
ARG EXTRA_APT=""
ARG EXTRA_CMAKE=""
RUN apt-get update && apt-get install -y --no-install-recommends \
    check cmake libbz2-dev libcurl4-openssl-dev libjson-c-dev libncurses-dev libpcre2-dev \
    libssl-dev libxml2-dev pkg-config python3-pytest zlib1g-dev ${EXTRA_APT} \
    && rm -rf /var/lib/apt/lists/*
COPY . /src
WORKDIR /src
RUN cmake -S . -B /build -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX=/opt/clamav \
    -DENABLE_CLAMONACC=OFF -DENABLE_EXAMPLES=OFF -DENABLE_JSON_SHARED=ON -DENABLE_MAN_PAGES=OFF \
    -DENABLE_MILTER=OFF -DENABLE_STATIC_LIB=OFF -DENABLE_SYSTEMD=OFF ${EXTRA_CMAKE} \
 && cmake --build /build -j"$(nproc)" && cmake --install /build

FROM debian:trixie-slim
ARG EXTRA_RUNTIME_APT=""
RUN apt-get update && apt-get install -y --no-install-recommends \
    libbz2-1.0 libcurl4t64 libjson-c5 libncurses6 libpcre2-8-0 libssl3t64 libxml2 zlib1g python3 ${EXTRA_RUNTIME_APT} \
    && rm -rf /var/lib/apt/lists/*
COPY --from=build /opt/clamav /opt/clamav
ENV PATH=/opt/clamav/bin:$PATH LD_LIBRARY_PATH=/opt/clamav/lib
