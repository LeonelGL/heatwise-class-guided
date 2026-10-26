FROM python:3.11-slim-bookworm
LABEL org.opencontainers.image.title="HEATWISE Class-guided Preprocessor"
LABEL org.opencontainers.image.version="0.2.0"
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
WORKDIR /app
COPY requirements-lock-python311.txt /app/
RUN pip install --no-cache-dir -r requirements-lock-python311.txt
COPY class_guided_processor.py /app/
WORKDIR /work
CMD ["python3", "/app/class_guided_processor.py", "--help"]
