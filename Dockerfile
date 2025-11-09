# Imagen base con Python
FROM python:3.12-slim

# Evita prompts
ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Actualiza y agrega FFmpeg + utilidades
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg ca-certificates git curl \
 && rm -rf /var/lib/apt/lists/*

# Instala dependencias
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copia el proyecto
COPY . .

# Gunicorn para producción (Flask WSGI)
# Si tu app arranca con "app.py", expón "app:app"
ENV PORT=10000
CMD ["gunicorn", "-b", "0.0.0.0:10000", "app:app"]
