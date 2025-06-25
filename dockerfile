FROM --platform=linux/arm64 python:3.10-slim-bookworm

LABEL description="MinerU Layout Analysis Service"

ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1-mesa-glx \
    libglib2.0-0 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY mineru_service.py .

RUN groupadd -r appuser && useradd -r -g appuser appuser

RUN mkdir -p /app/.cache && chown -R appuser:appuser /app
# Tell MinerU and other tools where the cache directory is
ENV MINERU_HOME="/app/.cache"
ENV XDG_CACHE_HOME="/app/.cache"

USER appuser

EXPOSE 8087

# --host 0.0.0.0 is crucial to make the service accessible from outside the container.
CMD ["uvicorn", "mineru_service:app", "--host", "0.0.0.0", "--port", "8087"]