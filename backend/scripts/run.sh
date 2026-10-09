#!/usr/bin/env bash
set -euo pipefail

alembic upgrade head
python -m scripts.seed
uvicorn app.main:app --host 0.0.0.0 --port 8000
