# Immagine base fissata per digest (python:3.11-slim al 2026-10-07).
FROM python:3.11-slim@sha256:0dd364ba7e10242f07755449e3a3d0e35f9efd987952737b90def6709ab0c5ce

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app/src \
    ESEF_PROJECT_ROOT=/app \
    PYTEST_ADDOPTS="-p no:cacheprovider"

WORKDIR /app

# Dipendenze con versioni e hash fissati (requirements.lock generato con uv pip compile).
# Dietro un proxy con ispezione TLS si può passare il certificato della CA come secret
# (non resta nell'immagine): docker build --secret id=ca_bundle,src=<file.pem> .
COPY requirements.lock ./
RUN --mount=type=secret,id=ca_bundle,required=false \
    if [ -s /run/secrets/ca_bundle ]; then export PIP_CERT=/run/secrets/ca_bundle; fi; \
    pip install --require-hashes -r requirements.lock

# Solo codice, configurazione e test: nessun dato nell'immagine (vedi .dockerignore).
COPY pyproject.toml README.md ./
COPY src ./src
COPY config ./config
COPY tests ./tests

RUN useradd --create-home --uid 10001 esef \
    && mkdir -p /app/data /app/annotations \
    && chown esef:esef /app/data /app/annotations
USER esef

# I dati si montano a runtime: docker run -v "$PWD/data:/app/data" ...
CMD ["python", "-m", "extraction.cli", "pipeline"]
