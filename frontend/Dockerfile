FROM node:20-alpine

WORKDIR /app

# Install dependencies
COPY package.json ./
RUN npm install

# Copy source
COPY . .

# Set internal API URL for Docker network at build time
ENV INTERNAL_API_URL=http://backend:8000

# Environment badge (NEXT_PUBLIC_* must be set before build for client-side inlining)
ARG NEXT_PUBLIC_ENV_LABEL=local
ENV NEXT_PUBLIC_ENV_LABEL=$NEXT_PUBLIC_ENV_LABEL

# Build for production
RUN npm run build

# Expose port
EXPOSE 3000

# Start
CMD ["npm", "start"]
