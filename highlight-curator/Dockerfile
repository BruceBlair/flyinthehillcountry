FROM python:3.12-slim

RUN apt-get update -qq && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY manifest_io.py curator.py score_images.py timelapse_builder.py cull_highlights.py vote_server.py scan_stars.py content_manager.py .

CMD ["python", "-u", "curator.py"]
