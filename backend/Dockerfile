# Build the virtualenv in one stage, carry only the result into the runtime
# image, so no build tooling or package index cache ships to production.
FROM python:3.13-slim AS build

COPY --from=ghcr.io/astral-sh/uv:0.9.7 /uv /bin/uv

WORKDIR /app
COPY pyproject.toml ./
COPY src ./src

RUN uv venv /opt/venv \
 && VIRTUAL_ENV=/opt/venv uv pip install --no-cache '.[service]'

FROM python:3.13-slim

RUN useradd --system --create-home --uid 10001 sift

COPY --from=build /opt/venv /opt/venv

WORKDIR /app
# Migrations run from this image too, as a one-off task before each deploy.
COPY alembic.ini ./
COPY migrations ./migrations

ENV PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

USER sift
EXPOSE 8000

CMD ["uvicorn", "sift.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
