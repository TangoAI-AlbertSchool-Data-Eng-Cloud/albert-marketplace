FROM python:3.9-slim
WORKDIR /app
COPY .env .
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY backend /app
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]