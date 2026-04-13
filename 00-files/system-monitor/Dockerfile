FROM python:3.12-slim

# Labels
LABEL org.opencontainers.image.title="system-monitor"
LABEL org.opencontainers.image.description="Live CPU, Memory and Network monitor (htop + nload style)"

# Install only what psutil needs at runtime
RUN apt-get update && apt-get install -y --no-install-recommends \
    procps \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .

# Run as non-root inside the container
RUN useradd -r -s /bin/false monitor
USER monitor

ENV PYTHONUNBUFFERED=1 \
    TERM=xterm-256color \
    REFRESH_RATE=1.0 \
    SHOW_LOOPBACK=false \
    BAR_WIDTH=30

ENTRYPOINT ["python", "app.py"]
