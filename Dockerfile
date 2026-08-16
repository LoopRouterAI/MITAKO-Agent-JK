FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg ca-certificates libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/* \
    && ffprobe -version >/dev/null

WORKDIR /app
COPY requirements.txt ./
RUN pip install -r requirements.txt
COPY . .

RUN useradd --create-home --uid 10001 mitako \
    && mkdir -p /app/data /app/logs /app/tmp \
    && chown -R mitako:mitako /app
USER mitako

EXPOSE 8015 7861
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8015"]
