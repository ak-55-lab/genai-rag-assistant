FROM python:3.11-slim

WORKDIR /srv

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .
COPY templates ./templates

ENV PYTHONUNBUFFERED=1

# Railway injects PORT at runtime; shell form so ${PORT} actually expands.
# Falls back to 8080 for local `docker run` without -e PORT.
CMD ["sh", "-c", "gunicorn --bind 0.0.0.0:${PORT:-8080} --workers 2 --threads 4 --timeout 300 app:app"]
