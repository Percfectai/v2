FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    libgomp1 \
    libegl1 \
    libgles2 \
    && rm -rf /var/lib/apt/lists/*

ENV MEDIAPIPE_DISABLE_GPU=1
ENV PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY percfect_motion_analyzer_v2.py .

ENV PORT=10000
EXPOSE 10000

CMD uvicorn percfect_motion_analyzer_v2:app --host 0.0.0.0 --port ${PORT} --workers 1