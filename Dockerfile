FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY log_parser.py .

ENTRYPOINT ["python", "log_parser.py"]
