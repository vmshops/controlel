# Admin builds this runner once; workflow steps never receive a Docker socket.
FROM python:3.14-bookworm
RUN python -c 'import sys; assert sys.version_info[:2] == (3, 14) and sys.version_info >= (3, 14, 2), sys.version' \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
       ca-certificates git build-essential pkg-config ffmpeg libffi-dev libssl-dev \
       libjpeg-dev zlib1g-dev libudev-dev libpcap0.8-dev libturbojpeg0 \
    && rm -rf /var/lib/apt/lists/*
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 PYTHONDONTWRITEBYTECODE=1
