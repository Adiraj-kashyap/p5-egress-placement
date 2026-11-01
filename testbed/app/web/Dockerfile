# Build from testbed/app: docker build -f web/Dockerfile -t p5-web:m07 .
FROM python:3.12-slim
WORKDIR /app
COPY web/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY common/counting.py web/main.py ./
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--no-server-header", "--no-date-header", "--no-access-log"]
