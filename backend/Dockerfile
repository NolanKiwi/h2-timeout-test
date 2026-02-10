FROM python:3.11-slim

# Install tcpdump and libpcap
RUN apt-get update && apt-get install -y tcpdump libpcap-dev gcc && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY app/ app/
COPY capture/ capture/

# Create capture directory
RUN mkdir -p /app/captures

EXPOSE 8000

# Start Uvicorn
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
