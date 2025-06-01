# Use an official Python runtime as a parent image
FROM python:3.9-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1
ENV FLASK_APP=run.py
ENV FLASK_RUN_HOST=0.0.0.0
#
# --- CRITICAL RUNTIME ENVIRONMENT VARIABLES ---
# The following environment variables MUST be set at runtime for the application to start:
#
# SECRET_KEY: A strong, unique secret key for Flask session security and other crypto.
#             Example: openssl rand -hex 32
#
# DATABASE_URL: The connection URI for the SQLAlchemy database.
#               Example (SQLite for dev/testing, adjust for production like PostgreSQL/MySQL):
#               sqlite:////app/data/app.db  (Note: if using SQLite, ensure /app/data is a persistent volume)
#               postgresql://user:password@host:port/dbname
#
# REDIS_URL: The connection URI for the Redis server, used for screen mirroring session storage.
#            Example: redis://myredisserver:6379/0
#
# LOG_LEVEL: (Optional) Sets the application log level. Defaults to INFO.
#            Examples: DEBUG, INFO, WARNING, ERROR
#
# --- ---------------------------------------- ---

# Set the working directory in the container
WORKDIR /app

# Optional: Create a non-root user to run the application for better security
# RUN addgroup --system app && adduser --system --ingroup app app
# USER app
# If using a non-root user, ensure file permissions are correct for /app and any volumes.

# Copy the requirements file into the container at /app
COPY requirements.txt .

# Install any needed packages specified in requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
# Gunicorn and eventlet are expected to be in requirements.txt now, or install explicitly:
# RUN pip install --no-cache-dir gunicorn eventlet # Already in requirements.txt from previous steps

# Copy the rest of the application code into the container at /app
COPY . .

# Expose the port the app runs on
EXPOSE 5000

# Define the command to run the application
# Uses Gunicorn with an Eventlet worker for Flask-SocketIO.
CMD ["gunicorn", "--worker-class", "eventlet", "-w", "1", "run:app", "--bind", "0.0.0.0:5000"]
