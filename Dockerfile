# Immagine del Cloud Run Job: esegue `jobist run` e termina.
FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    POETRY_CACHE_DIR=/tmp/poetry_cache

WORKDIR /app

# Dipendenze prima del codice: il layer si ricostruisce solo se cambia il lock.
COPY pyproject.toml poetry.lock ./
RUN pip install poetry \
    && poetry config virtualenvs.create false \
    && poetry install --only main --no-interaction --no-ansi --no-root \
    && rm -rf "$POETRY_CACHE_DIR"

COPY . .

# Il database locale vive in /data (montabile come volume in locale).
ENV JOBIST_DB_PATH=/data/jobist.sqlite3

RUN useradd --system --uid 1000 jobist && mkdir /data && chown jobist /data
USER jobist

ENTRYPOINT ["python", "-m", "jobist"]
CMD ["run"]
