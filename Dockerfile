# Use an official Python runtime as a parent image
FROM python:3.10-slim

# Set the working directory in the container
WORKDIR /app

# Copy requirements first to leverage Docker cache
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code
COPY . .

# Expose the port Flask runs on
EXPOSE 8000

# Command to run the application using Gunicorn (production server)
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "app:app"]