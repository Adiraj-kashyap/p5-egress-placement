# Build from testbed/app: docker build -f api/Dockerfile -t p5-api:m07 .
FROM python:3.12-slim
WORKDIR /app
COPY api/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY common/counting.py api/main.py ./
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--no-server-header", "--no-date-header", "--no-access-log"]
