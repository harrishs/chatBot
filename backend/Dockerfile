# Use official Python image as base
FROM python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# Set working directory
WORKDIR /app

# Copy wait script inside working directory
COPY wait-for-it.sh /wait-for-it.sh
RUN chmod +x /wait-for-it.sh

# Install system dependencies
RUN apt-get update && apt-get install -y \
    libpq-dev gcc netcat-openbsd --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --upgrade pip
RUN pip install -r requirements.txt

# Copy the rest of your app
COPY . .

# Expose port
EXPOSE 8000

# Default CMD
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]
