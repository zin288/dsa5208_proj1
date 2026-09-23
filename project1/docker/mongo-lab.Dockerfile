FROM mongo:8.0.32-noble

USER root

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       iptables \
       iproute2 \
    && rm -rf /var/lib/apt/lists/*
