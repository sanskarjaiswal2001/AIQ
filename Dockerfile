# ===========================================================================
# AIQ — single-image mothership (FastAPI server + static dashboard)
# ===========================================================================
# Multi-stage build:
#   1. builder  — install Python deps into /install (keeps final image lean)
#   2. runtime  — copy deps + server code + dashboard, run uvicorn
#
# The server modules use *bare* imports (``import database``, ``from models
# import …``) rather than package-qualified imports.  We therefore set
# PYTHONPATH=/app/server so Python resolves those modules without touching
# the server source code.
# ===========================================================================

# ---------- stage 1: dependency builder ----------
FROM python:3.11-slim AS builder
WORKDIR /build
COPY server/requirements.txt .
# Install dependencies into a separate directory so we can copy just them
# into the final image (no pip/cache bloat).
RUN pip install --no-cache-dir --target=/install -r requirements.txt

# ---------- stage 2: runtime ----------
FROM python:3.11-slim
WORKDIR /app

# Copy pre-built dependencies from the builder stage.
COPY --from=builder /install /usr/local/lib/python3.11/site-packages/

# Copy the server source (bare-import modules) and the static dashboard.
COPY server/ /app/server/
COPY dashboard/ /app/dashboard/

# --- runtime configuration ---
# PYTHONPATH points at the server dir so bare imports (database, models,
# rules_meta, recommendations) resolve at runtime.
ENV PYTHONPATH=/app/server \
    DB_PATH=/data/aiq.db \
    DASHBOARD_DIR=/app/dashboard \
    AIQ_ADMIN_KEY="" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

EXPOSE 8000
VOLUME ["/data"]

# ``main:app`` (not ``server.main:app``) because PYTHONPATH=/app/server puts
# main.py on the import path directly.
CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
