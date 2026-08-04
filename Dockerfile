FROM python:3.11-slim

WORKDIR /app

# Install dependencies OS untuk PostgreSQL & GCC
RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt-get/lists/*

# Copy & Install Python packages
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy seluruh source code
COPY . .

# Jalankan script main.py secara langsung
CMD ["python", "app/main.py"]