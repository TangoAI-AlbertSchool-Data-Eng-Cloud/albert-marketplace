# Live traffic: the load generator (docs/build-spec.md §5.5). Installs only the "live" dependency group.
FROM ghcr.io/astral-sh/uv:0.9.30-python3.12-bookworm-slim

ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_COMPILE_BYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /generators
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-cache --no-default-groups --group live \
    && useradd --create-home --uid 10001 generator
COPY europe.py ./
COPY history/calibration.json history/
COPY live/ live/

# Settings come from the environment at run time (see compose.yaml)
USER generator
CMD ["python", "live/traffic.py"]
