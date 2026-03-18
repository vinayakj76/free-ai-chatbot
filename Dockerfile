# File: Dockerfile

# 1. Base Image
FROM python:3.10-slim

# 2. Set working directory
WORKDIR /app

# 3. Install system dependencies (needed for some python packages)
RUN apt-get update && apt-get install -y gcc libpq-dev

# 4. Install Python dependencies
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 5. Copy Application Code
COPY backend/ ./backend/
COPY frontend/ ./frontend/

# 6. Create data directories
RUN mkdir -p data/sqlite_db data/chroma_db

# 7. Set environment variables
ENV PYTHONUNBUFFERED=1

# 8. Expose Port
EXPOSE 8000

# 9. Run the application
# We use 0.0.0.0 to allow external connections inside the container
CMD ["uvicorn", "backend.app:app", "--host", "0.0.0.0", "--port", "8000"]