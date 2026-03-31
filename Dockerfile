FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY scanner.py .
COPY config.yaml .

CMD ["python", "scanner.py"]
