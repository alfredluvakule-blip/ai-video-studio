FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg espeak-ng fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# Natural-sounding narrator voices (Piper, runs on the CPU). Kept as its own step so a
# download problem here does not stop the app from building: the robotic eSpeak voice
# is used instead, and the Settings page shows that Piper is missing.
RUN pip install --no-cache-dir "piper-tts>=1.3,<2" \
    || echo "WARNING: piper-tts could not be installed; narration will use eSpeak NG"
COPY app ./app
ENV STORAGE_DIR=/data
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
