FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HOME=/home/app

WORKDIR /app

RUN apt-get update \
    && apt-get install --no-install-recommends -y tesseract-ocr tesseract-ocr-eng tesseract-ocr-por \
    && rm -rf /var/lib/apt/lists/* \
    && addgroup --system app \
    && adduser --system --ingroup app --home /home/app app

COPY pyproject.toml ./
COPY app ./app
COPY alembic.ini ./
COPY alembic ./alembic
# Local profiles use PaddleOCR; other profiles can enable OpenCV preprocessing.
RUN pip install ".[local-ocr]"
RUN apt-get update \
    && apt-get install --no-install-recommends -y libgl1 \
    && rm -rf /var/lib/apt/lists/*
RUN mkdir -p /data/uploads /home/app/.paddlex \
    && chown -R app:app /data/uploads /home/app

USER app

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
