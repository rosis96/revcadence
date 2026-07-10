# Web runs migrations, then serves. Worker does NOT migrate (avoids races);
# if it boots before the web migrated, it just retries via restart policy.
web: python -m alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port $PORT
worker: python -m app.workers.runner
