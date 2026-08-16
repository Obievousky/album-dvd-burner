FROM python:3.12-slim-bookworm

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    dvdauthor \
    xorriso \
    eject \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt pyproject.toml README.md ./
COPY src ./src

RUN pip install --no-cache-dir .

COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENV DATA_ROOT=/data \
    DVD_DEVICE=/dev/sr0 \
    DVD_STANDARD=ntsc \
    WEB_PORT=8080

EXPOSE 8080

VOLUME ["/data"]

ENTRYPOINT ["/entrypoint.sh"]
