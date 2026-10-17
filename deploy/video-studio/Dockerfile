FROM python:3.12-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg fonts-dejavu-core && rm -rf /var/lib/apt/lists/*
COPY . .
RUN pip install --no-cache-dir -e '.[test]' runwayml
ENV PYTHONUNBUFFERED=1
CMD ["gunicorn","main:app","--bind","0.0.0.0:8000","--workers","2","--timeout","120"]
