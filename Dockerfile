FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /srv

# Install only the runtime dependencies declared in pyproject.toml; the app runs from source so
# that queries/ stays next to app/.
COPY --from=ghcr.io/astral-sh/uv:0.10.4 /uv /usr/local/bin/uv
COPY pyproject.toml ./
RUN uv pip install --system --no-cache -r pyproject.toml

COPY app ./app
COPY queries ./queries

RUN useradd --system --uid 10001 --no-create-home api
USER api

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3).status == 200 else 1)"]

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
