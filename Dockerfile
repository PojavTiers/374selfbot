FROM python:3.11-slim

# Prevent Python from writing pyc files & buffering stdout (good for Railway logs)
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install deps first for better layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the bot
COPY . .

# Run the bot
CMD ["python", "-u", "main.py"]