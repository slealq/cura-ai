FROM node:20-alpine

WORKDIR /app

# Install dependencies
COPY package.json ./
RUN npm install

# Copy source
COPY . .

# Set internal API URL for Docker network at build time
ENV INTERNAL_API_URL=http://backend:8000

# Build for production
RUN npm run build

# Expose port
EXPOSE 3000

# Start
CMD ["npm", "start"]
