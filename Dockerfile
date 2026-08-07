FROM python:3.11-slim

# Install dos2unix untuk netralisir CRLF otomatis
RUN apt-get update && apt-get install -y dos2unix && rm -rf /var/lib/apt-get/lists/*

WORKDIR /app

COPY requirements.txt .

# Konversi requirements.txt ke LF sebelum di-install pip
RUN dos2unix requirements.txt && pip install --no-cache-dir -r requirements.txt

COPY . .

# Konversi semua file python dan shell script ke LF
RUN find . -type f \( -name "*.py" -o -name "*.sh" -o -name "*.yml" \) -exec dos2unix {} +