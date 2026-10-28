FROM python:3.13-slim
COPY --from=ghcr.io/astral-sh/uv:0.13.6 /uv /bin/uv

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_NO_DEV=1
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-install-project

COPY app ./app
RUN useradd --create-home app && mkdir -p /app/data && chown app /app/data
USER app
ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 3000
CMD ["fastapi", "run", "app/main.py", "--port", "3000"]
