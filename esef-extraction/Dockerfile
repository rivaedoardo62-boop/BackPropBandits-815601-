# Pipeline di estrazione ESEF. Nessun dato nell'immagine: la cartella dei dati
# si monta a runtime in /app/data (vedi README).
# Immagine base fissata per digest (python:3.11-slim, verificata il 2026-10-07).
FROM python:3.11-slim@sha256:0dd364ba7e10242f07755449e3a3d0e35f9efd987952737b90def6709ab0c5ce

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app/src \
    PYTEST_ADDOPTS="-p no:cacheprovider" \
    ESEF_DATA_DIR=/app/data \
    ESEF_CONFIG_DIR=/app/config

WORKDIR /app

# Dipendenze con versioni e hash fissati (requirements.lock, generato da pyproject.toml).
# Dietro un proxy con ispezione TLS si puo' passare la CA aziendale come secret di build
# (non resta nell'immagine): docker build --secret id=ca_bundle,src=/percorso/ca.pem .
COPY requirements.lock ./
RUN --mount=type=secret,id=ca_bundle,required=false \
    if [ -s /run/secrets/ca_bundle ]; then export PIP_CERT=/run/secrets/ca_bundle; fi \
    && pip install --require-hashes --no-deps -r requirements.lock

# Codice e configurazione appartengono a root e non sono modificabili dall'utente di esecuzione.
COPY pyproject.toml README.md ./
COPY src ./src
COPY config ./config
COPY tests ./tests

RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin esef \
    && mkdir -p /app/data \
    && chown esef:esef /app/data

USER esef
VOLUME ["/app/data"]

ENTRYPOINT ["python", "-m", "extraction"]
CMD ["run"]
