FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONUNBUFFERED=1

CMD exec gunicorn -w 2 -b 0.0.0.0:${PORT:-8003} app:app
