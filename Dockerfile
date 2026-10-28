FROM python:3.11-slim

# System deps for opencv, pillow, playwright, ffmpeg
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install playwright browsers
RUN playwright install --with-deps chromium

COPY . .

EXPOSE 10000

# Important: without inline workers, postgres-queued jobs sit forever (no worker service on this Render).
ENV STUDIO_QUEUE_BACKEND=postgres
ENV STUDIO_INLINE_WORKERS=1
ENV STUDIO_MAX_CONCURRENT_JOBS=8

CMD ["gunicorn", "app:app", "--bind", "0.0.0.0:10000", "--workers", "2", "--threads", "4", "--worker-class", "gthread", "--timeout", "120"]
