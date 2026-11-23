FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 iproute2 iputils-ping traceroute tcpdump tshark curl \
    apache2-utils net-tools procps ethtool && rm -rf /var/lib/apt/lists/*
