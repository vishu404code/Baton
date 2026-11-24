FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Install dependencies first so code edits don't bust the layer cache.
COPY pyproject.toml ./
# Install only the dependencies; the app itself runs from /app via PYTHONPATH.
RUN mkdir -p app && touch app/__init__.py \
    && pip install ".[dev]" \
    && pip uninstall -y baton-backend \
    && rm -rf app

ENV PYTHONPATH=/app

COPY . .
RUN chmod +x docker-entrypoint.sh

EXPOSE 8000
ENTRYPOINT ["./docker-entrypoint.sh"]
