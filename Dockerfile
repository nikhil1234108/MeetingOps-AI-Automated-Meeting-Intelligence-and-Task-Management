# Use an official lightweight Python runtime as a parent image
FROM python:3.12-slim

# Set environment variables for Python and application defaults
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HOST=0.0.0.0 \
    PORT=8000 \
    RELOAD=false

# Set the working directory in the container
WORKDIR /app

# Copy dependency definition to leverage Docker cache
COPY requirements.txt .

# Install python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code
COPY . .

# Expose port 8000 for the FastAPI web server
EXPOSE 8000

# Command to run the application
CMD ["python", "workflows/run_pipeline.py", "--serve"]
