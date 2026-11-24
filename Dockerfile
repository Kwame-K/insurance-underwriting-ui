FROM python:3.11-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:0.10.7 /uv /uvx /bin/

COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src ./src
RUN uv sync --frozen --no-dev


FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH" \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false

WORKDIR /app

RUN useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /app

COPY --from=builder --chown=appuser:appuser /app /app

COPY --chown=appuser:appuser .streamlit ./.streamlit


USER appuser

EXPOSE 8501

CMD ["streamlit", "run", "src/insurance_underwriting_ui/app.py", "--server.port=8501", "--server.address=0.0.0.0", "--server.headless=true"]
