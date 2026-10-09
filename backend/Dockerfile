FROM python:3.13-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy project
COPY . .

# Create non-root user
# deal_media создаётся заранее: именованный том при первом подключении берёт
# владельца каталога из образа. Без этого том достался бы root, и фото из
# переписки по сделкам не сохранялись бы
RUN mkdir -p /app/deal_media /app/uploads/products && useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

# Run application (without --reload for production)
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
