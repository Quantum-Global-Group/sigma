FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

# Worker reuses the api service's requirements (same Python deps).
COPY apps/api/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy api code (worker imports markets/, ml/, execution/, etc. from it) plus
# the worker entry point itself.
COPY apps/api ./api
COPY apps/worker ./worker

ENV PYTHONPATH="/app/api:/app"

CMD ["python", "-m", "worker.main"]
