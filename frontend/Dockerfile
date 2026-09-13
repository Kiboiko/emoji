# Build stage
FROM node:22-alpine AS builder

WORKDIR /app

ARG VITE_API_URL
ARG VITE_BOT_USERNAME
ENV VITE_API_URL=$VITE_API_URL
ENV VITE_BOT_USERNAME=$VITE_BOT_USERNAME

# Install dependencies
COPY package*.json ./
RUN npm install

# Copy source code
COPY . .

# Build app
RUN npm run build

# Final stage - keep container alive to share dist volume
FROM node:22-alpine

WORKDIR /app

COPY --from=builder /app/dist ./dist

# Keep container running
CMD ["tail", "-f", "/dev/null"]
