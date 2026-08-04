FROM node:20-alpine

WORKDIR /app

COPY package*.json ./
RUN npm install

COPY . .

EXPOSE 3000

# Use Next.js development server
CMD ["npm", "run", "dev"]
