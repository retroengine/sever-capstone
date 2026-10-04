# The SEVER-DB review demo as a container. Everything it needs is inside the image except the data,
# which compose.yaml mounts read-only at /data (the folder ../datasets of this repo).
#
#   scripts/demo.sh docker-build                # stamps the image with the current git commit
#   scripts/demo.sh docker test | run | repl | verify <anchors.json> <file.cert>...
#
# bookworm's libsodium23 is 1.0.18, the version the demo was built and tested against.
FROM python:3.13-slim-bookworm

RUN apt-get update \
 && apt-get install -y --no-install-recommends libsodium23 \
 && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.12.2 /uv /usr/local/bin/uv

ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    PYTHONHASHSEED=0 \
    PYTHONPATH=python \
    SEVER_DATASETS=/data
WORKDIR /demo

# Dependencies first (cached layer), from the lockfile only.
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen

COPY python ./python
COPY tests ./tests
COPY scripts ./scripts
COPY docs ./docs
RUN mkdir -p results

# The ledger records which code ran; there is no git inside the image, so the build stamps it.
ARG SEVER_GIT_COMMIT=unknown
ARG SEVER_GIT_DIRTY=
ENV SEVER_GIT_COMMIT=${SEVER_GIT_COMMIT} SEVER_GIT_DIRTY=${SEVER_GIT_DIRTY}

ENTRYPOINT ["sh", "scripts/entrypoint.sh"]
CMD ["repl"]
