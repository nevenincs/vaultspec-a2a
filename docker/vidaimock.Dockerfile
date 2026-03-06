FROM ubuntu:22.04

RUN apt-get update && \
    apt-get install -y curl tar ca-certificates && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

RUN curl -LO https://github.com/vidaiUK/VidaiMock/releases/download/v0.1.2/vidaimock-linux-x64.tar.gz && \
    tar -xzf vidaimock-linux-x64.tar.gz && \
    rm vidaimock-linux-x64.tar.gz && \
    mv vidaimock/vidaimock /usr/local/bin/vidaimock && \
    chmod +x /usr/local/bin/vidaimock && \
    rm -rf vidaimock

EXPOSE 8100

CMD ["vidaimock", "--port", "8100", "--host", "0.0.0.0", "--config-dir", "/app/tapes"]
