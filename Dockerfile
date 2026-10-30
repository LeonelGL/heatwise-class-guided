FROM python:3.11-slim-bookworm
ARG RELEASE_VERSION=0.3.2
ARG SOURCE_REPOSITORY=https://github.com/LeonelGL/heatwise-class-guided
LABEL org.opencontainers.image.title="HEATWISE Class-guided Preprocessor"
LABEL org.opencontainers.image.version="${RELEASE_VERSION}"
LABEL org.opencontainers.image.source="${SOURCE_REPOSITORY}"
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
RUN apt-get update && apt-get install -y --no-install-recommends libexpat1 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements-lock-python311.txt /app/
RUN pip install --no-cache-dir -r requirements-lock-python311.txt
RUN python -c "import numpy, scipy, pandas, rasterio, openpyxl, sklearn, pyproj, pystac"
COPY class_guided_processor.py /app/
WORKDIR /work
CMD ["python3", "/app/class_guided_processor.py", "--help"]
