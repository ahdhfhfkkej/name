FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && useradd --create-home runner
COPY *.py ./
USER runner
ENV PORT=8080
CMD ["sh", "-c", "exec uvicorn mobile_api:app --host 0.0.0.0 --port ${PORT:-8080} --workers 1 --no-access-log"]
