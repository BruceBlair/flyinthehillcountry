FROM python:3.12-slim

RUN apt-get update -qq && apt-get install -y --no-install-recommends \
    ffmpeg libgl1 libglib2.0-0 curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY sky_watcher.py scout_heatmap.py ./
# stitch.py is mounted from the project root at /app/stitch.py

CMD ["python", "-u", "sky_watcher.py"]
