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

# The container stays alive to share the /app/dist volume with nginx
# Use a simple command to keep container running
CMD ["tail", "-f", "/dev/null"]
