FROM python:3.11-slim

WORKDIR /srv

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY data ./data

# results/ is where run history lives -- mount this as a volume so eval
# history survives container restarts/rebuilds (see docker-compose.yml).
RUN mkdir -p results/raw results/runs

ENV PYTHONUNBUFFERED=1 \
    PORT=8080

EXPOSE 8080

# Single worker: eval-run status is tracked in-process (in-memory), so
# multiple workers would each have their own view of "is a run in progress".
# --threads lets it still serve status-polling requests while a background
# eval thread is running inside the same worker.
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "1", "--threads", "8", "--timeout", "600", "app.dashboard:app"]
