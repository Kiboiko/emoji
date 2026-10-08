# Build stage
FROM node:22-alpine AS builder

WORKDIR /app

ARG VITE_API_URL
ARG VITE_BOT_USERNAME
ARG SITE_URL=http://localhost:8080
ARG VITE_DEV_AUTH=false
ENV VITE_DEV_AUTH=$VITE_DEV_AUTH
ARG APP_NAME="Gram Market"
ENV VITE_API_URL=$VITE_API_URL
ENV VITE_BOT_USERNAME=$VITE_BOT_USERNAME

# Install dependencies
COPY package*.json ./
RUN npm install

# Copy source code
COPY . .

# Манифест TON Connect должен указывать на реальный домен приложения:
# кошелёк скачивает его сам и сверяет origin. Зашивать localhost в образ
# нельзя, поэтому подставляем домен на сборке.
# Иконка — PNG 180×180: SVG кошельки не показывают, а прежний vite.svg в
# сборке и не существовал — при подключении кошелёк видел пустое место.
RUN echo "{\"url\":\"$SITE_URL\",\"name\":\"$APP_NAME\",\"iconUrl\":\"$SITE_URL/icon-180.png\"}" > public/tonconnect-manifest.json

# Build app
RUN npm run build

# Final stage — раздача собранных файлов через общий том с nginx.
#
# ВАЖНО: dist НЕ кладётся сразу в /app/dist. Docker наполняет именованный том
# из образа только если том ПУСТОЙ, поэтому при таком раскладе каждая
# пересборка после первой молча отдавала бы старую сборку — nginx продолжал
# бы раздавать файлы из тома, созданного когда-то давно.
#
# Поэтому сборка лежит в /app/build, а на старте контейнера копируется в том.
FROM node:22-alpine

WORKDIR /app

COPY --from=builder /app/dist ./build

CMD ["sh", "-c", "rm -rf /app/dist/* /app/dist/.[!.]* 2>/dev/null; cp -a /app/build/. /app/dist/ && echo 'dist синхронизирован' && tail -f /dev/null"]
