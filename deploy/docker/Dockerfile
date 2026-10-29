# syntax=docker/dockerfile:1

# Build the Vue frontend separately so the runtime image only contains its
# production assets and the Python service.
# pnpm 11.x 要求 Node >= 22.13（依赖 node:sqlite 内置模块），故用 node:22
FROM node:22-bookworm-slim AS frontend-builder
ARG NPM_REGISTRY=https://mirrors.cloud.tencent.com/npm
ENV COREPACK_NPM_REGISTRY=${NPM_REGISTRY}
WORKDIR /src/webapp/frontend

COPY webapp/frontend/package.json webapp/frontend/pnpm-lock.yaml webapp/frontend/pnpm-workspace.yaml ./
RUN corepack enable && corepack prepare pnpm@11.9.0 --activate
RUN pnpm install --frozen-lockfile --registry="${NPM_REGISTRY}"

COPY webapp/frontend/ ./
RUN pnpm run build

FROM python:3.12-slim-bookworm AS python-builder
ARG PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
ARG UV_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_CACHE_DIR=/tmp/uv-cache \
    UV_LINK_MODE=copy \
    UV_HTTP_CONNECT_TIMEOUT=10 \
    UV_HTTP_TIMEOUT=60 \
    UV_HTTP_RETRIES=2 \
    UV_CONCURRENT_DOWNLOADS=8 \
    PIP_INDEX_URL=${PIP_INDEX_URL} \
    UV_INDEX_URL=${UV_INDEX_URL}
WORKDIR /src

RUN pip install --no-cache-dir uv==0.12.7

COPY pyproject.toml uv.lock README.zh-CN.md ./

# Export exact versions and artifact hashes from the unchanged lockfile. Frozen
# sync uses its locked download URLs, so install the export through our mirror.
# Keep third-party dependencies cached when only application code changes.
RUN --mount=type=cache,id=mpau-uv-cache,target=/tmp/uv-cache \
    uv export --frozen --no-dev --extra web --no-emit-project \
        --format requirements-txt --output-file /tmp/mpau-web-requirements.txt \
    && uv venv --python python3.12 --no-python-downloads "${UV_PROJECT_ENVIRONMENT}" \
    && uv pip sync --python "${UV_PROJECT_ENVIRONMENT}/bin/python" \
        --require-hashes --index-url "${UV_INDEX_URL}" /tmp/mpau-web-requirements.txt

COPY local_agent/ local_agent/
COPY uploader/ uploader/
COPY utils/ utils/
COPY webapp/ webapp/
COPY --from=frontend-builder /src/webapp/frontend/dist /src/webapp/frontend/dist

# Install a self-contained package so no paths from this build stage leak into
# the runtime image.
RUN --mount=type=cache,id=mpau-uv-cache,target=/tmp/uv-cache \
    uv pip install --python "${UV_PROJECT_ENVIRONMENT}/bin/python" \
        --no-deps --no-editable --index-url "${UV_INDEX_URL}" .

# Check the installed application before replacing the running service.
RUN cd /tmp \
    && MPAU_DATA_DIR=/tmp/mpau-startup-check /opt/venv/bin/python -c "from webapp.api.main import app; assert app.state.mysql_database is not None" \
    && rm -rf /tmp/mpau-startup-check

FROM python:3.12-slim-bookworm AS runtime
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    MPAU_BIND_HOST=0.0.0.0 \
    MPAU_PORT=8788 \
    MPAU_DATA_DIR=/var/lib/mpau/data \
    MPAU_AGENT_INSTALLER_PATH=/var/lib/mpau/releases/MPAU-Agent-Setup.exe
WORKDIR /app

COPY --from=python-builder /opt/venv /opt/venv
COPY --from=python-builder /src/ /app/

RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin mpau \
    && mkdir -p /var/lib/mpau/data /var/lib/mpau/releases \
    && chown -R mpau:mpau /app /var/lib/mpau
USER mpau

EXPOSE 8788
VOLUME ["/var/lib/mpau/data"]
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8788/api/health', timeout=3)"]
CMD ["mpau-web"]
