# VidaiMock deterministic mock server for the integration certification stack.
# The release is pinned so the service-topology slice is reproducible.

FROM python:3.13-slim-bookworm

ARG TARGETARCH
ARG VIDAIMOCK_VERSION=v0.1.3

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

RUN set -eux; \
    arch="${TARGETARCH:-$(uname -m)}"; \
    case "${arch}" in \
      amd64|x86_64) asset="vidaimock-linux-x64.tar.gz" ;; \
      arm64|aarch64) asset="vidaimock-linux-arm64.tar.gz" ;; \
      *) echo "Unsupported TARGETARCH: ${arch}" >&2; exit 1 ;; \
    esac; \
    checksum_asset="${asset%.tar.gz}.sha256"; \
    mkdir -p /tmp/vidaimock; \
    curl -fsSL "https://github.com/vidaiUK/VidaiMock/releases/download/${VIDAIMOCK_VERSION}/${checksum_asset}" -o /tmp/vidaimock/vidaimock.sha256; \
    curl -fsSL "https://github.com/vidaiUK/VidaiMock/releases/download/${VIDAIMOCK_VERSION}/${asset}" -o "/tmp/vidaimock/${asset}"; \
    (cd /tmp/vidaimock && sha256sum -c vidaimock.sha256); \
    tar -xzf "/tmp/vidaimock/${asset}" -C /tmp/vidaimock; \
    binary="$(find /tmp/vidaimock -maxdepth 2 -type f -name vidaimock | head -n 1)"; \
    test -n "${binary}"; \
    install -m 0755 "${binary}" /usr/local/bin/vidaimock

WORKDIR /opt/vidaimock
COPY src/vaultspec_a2a/team/presets/mock/tapes/ ./tapes/

EXPOSE 8100

HEALTHCHECK --interval=5s --timeout=2s --retries=20 --start-period=5s CMD python -c "import socket, sys; sock = socket.socket(); sock.settimeout(1); sys.exit(0 if sock.connect_ex(('127.0.0.1', 8100)) == 0 else 1)"

CMD ["/usr/local/bin/vidaimock", "--config-dir", "/opt/vidaimock/tapes"]
