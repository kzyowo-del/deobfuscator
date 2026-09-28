FROM python:3.13-slim

RUN apt-get update && apt-get install -y git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY . .

RUN chmod +x /app/Deobfuscator/deobf/bin/luau* 2>/dev/null || true

RUN pip install flask

CMD ["python", "main.py"]
