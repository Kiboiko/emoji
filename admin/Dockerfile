FROM node:20-alpine

WORKDIR /app
ARG VITE_API_URL
ENV VITE_API_URL=$VITE_API_URL

# Install dependencies
COPY package*.json ./
RUN npm ci

# Copy source code
COPY . .

# Build production assets
RUN npm run build

# Сборка переносится из dist в build, а в том копируется на старте контейнера.
#
# ВАЖНО: Docker наполняет именованный том из образа только если том ПУСТОЙ.
# Если оставить готовую сборку прямо в /app/dist, то каждая пересборка после
# первой молча отдавала бы старые файлы: nginx продолжал бы раздавать
# содержимое тома, созданного когда-то давно.
RUN mv dist build

CMD ["sh", "-c", "rm -rf /app/dist/* /app/dist/.[!.]* 2>/dev/null; cp -a /app/build/. /app/dist/ && echo 'dist синхронизирован' && tail -f /dev/null"]
