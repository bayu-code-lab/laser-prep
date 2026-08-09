FROM python:3.12-slim

# opencv-python-headless still needs libglib at runtime
RUN apt-get update && apt-get install -y --no-install-recommends libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000
# ponytail: run uvicorn directly so we bind 0.0.0.0 (app.py's __main__ binds 127.0.0.1, unreachable from host)
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
