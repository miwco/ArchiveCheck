# ArchiveCheck web app — single container for on-prem deployment.
FROM python:3.10-slim

# System tools: ffmpeg, Tesseract (+ Swedish/English), Chromaprint (fpcalc), libgomp (TensorFlow).
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
        tesseract-ocr tesseract-ocr-swe tesseract-ocr-eng \
        libchromaprint-tools \
        libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Python deps first (layer cache). Core (incl. numpy<2 + inaSpeechSegmenter/TensorFlow) + web.
COPY requirements.txt ./requirements.txt
COPY web/requirements.txt ./web-requirements.txt
RUN pip install --no-cache-dir -r requirements.txt -r web-requirements.txt

# App code (see .dockerignore for what's excluded).
COPY archivecheck ./archivecheck
COPY web ./web
COPY end_credits_titles.txt ./end_credits_titles.txt

# Pre-download the inaSpeechSegmenter model weights at build time (avoids a slow
# first request). Non-fatal if offline during build.
RUN python -c "from inaSpeechSegmenter import Segmenter; Segmenter()" || true

ENV VC_DATA_DIR=/data
EXPOSE 8000

# Keys + VC_ACCESS_CODE / VC_SESSION_SECRET come from the environment (env_file).
CMD ["uvicorn", "web.app:app", "--host", "0.0.0.0", "--port", "8000"]
