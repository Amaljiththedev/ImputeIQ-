FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000
CMD ["uvicorn", "app.main:combined_app", "--host", "0.0.0.0", "--port", "8000", "--reload", "--reload-dir", "app/api", "--reload-dir", "app/auth", "--reload-dir", "app/core", "--reload-dir", "app/jobs", "--reload-dir", "app/models", "--reload-dir", "app/schemas", "--reload-exclude", "data/*", "--reload-exclude", "*.csv", "--reload-exclude", "*.db"]
