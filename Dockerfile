# Use an official Python runtime as a parent image
FROM python:3.10-slim

# Install system dependencies needed for PostgreSQL and C-based extensions
RUN apt-get update && apt-get install -y \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Set the working directory in the container
WORKDIR /app

# Copy requirements first to leverage Docker cache
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code
COPY . .

# Expose the port Render expects (10000)
EXPOSE 10000

# Run using Gunicorn, binding to 10000
CMD ["gunicorn", "--bind", "0.0.0.0:10000", "app:app"]