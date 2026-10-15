FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY core/ core/
COPY static/ static/
COPY server.py .

ENV PORT=7866 \
    KATARIBE_DATA=/data \
    KATARIBE_CACHE=/data/cache
VOLUME ["/data"]
EXPOSE 7866
CMD ["python", "server.py"]
