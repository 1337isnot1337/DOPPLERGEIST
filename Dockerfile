FROM python:3.12-slim-bookworm AS build

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /build
COPY pyproject.toml setup.py MANIFEST.in README.md LICENSE ./
COPY licenses/ ./licenses/
COPY src/ ./src/
RUN CC=gcc python -m pip wheel --wheel-dir /wheels .

FROM python:3.12-slim-bookworm AS runtime

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg libsndfile1 \
    && rm -rf /var/lib/apt/lists/*
COPY --from=build /wheels /tmp/wheels
RUN python -m pip install --no-index --find-links=/tmp/wheels dopplergeist \
    && python -m pip check \
    && python -c "from dopplergeist import _native_ridge, _native_acoustic, _native_cpa, _native_index" \
    && rm -rf /tmp/wheels
RUN useradd --create-home --uid 10001 --user-group dopplergeist \
    && mkdir -p /data/jobs /home/dopplergeist/.cache/dopplergeist \
    && chown -R dopplergeist:dopplergeist /data /home/dopplergeist
WORKDIR /data
USER 10001:10001
EXPOSE 8765
# Reuse the service's KeyboardInterrupt shutdown path to stop its job workers.
STOPSIGNAL SIGINT
ENTRYPOINT ["dopplergeist"]
CMD ["serve", "--host", "0.0.0.0", "--port", "8765", "--jobs", "/data/jobs"]

# Only Fly's explicit build target initializes a newly mounted root-owned volume.
FROM runtime AS fly
USER root
COPY deploy/fly_start.py /usr/local/bin/dopplergeist-fly-start.py
ENTRYPOINT ["python", "/usr/local/bin/dopplergeist-fly-start.py"]
CMD ["serve", "--host", "0.0.0.0", "--port", "8765", "--jobs", "/data/jobs", "--online", "--max-runtime", "14400"]

# Preserve the default local image, including its non-root startup user.
FROM runtime AS default
