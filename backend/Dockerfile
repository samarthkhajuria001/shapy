FROM python:3.11-slim

WORKDIR /app

# Copy requirements from backend/
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the backend code
COPY backend/ .

# Startup Command
# Respects Railway's $PORT variable
CMD ["sh", "-c", "python scripts/index_documents.py && uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]