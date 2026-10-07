# Immagine della pipeline. Nessun dato viene copiato: data/ (e annotations/)
# si montano a runtime come volume, vedi README.
# python:3.11-slim fissata per digest (risolta il 2026-10-07); per aggiornarla
# vedi README, "Aggiornare dipendenze e immagine".
FROM python:3.11-slim@sha256:0dd364ba7e10242f07755449e3a3d0e35f9efd987952737b90def6709ab0c5ce

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app/src \
    ESEF_DATA_DIR=/app/data \
    ESEF_CONFIG_DIR=/app/config

WORKDIR /app

# Dipendenze fissate con hash (lock generato da pyproject.toml).
COPY requirements.lock ./
RUN pip install --require-hashes -r requirements.lock

COPY pyproject.toml README.md ./
COPY src ./src
COPY config ./config
COPY tests ./tests

RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin esef \
    && mkdir -p /app/data \
    && chown esef:esef /app/data
USER esef

VOLUME ["/app/data"]
ENTRYPOINT ["python", "-m", "extraction"]
CMD ["pipeline"]
