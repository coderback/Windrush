FROM node:20-slim
WORKDIR /app
COPY package.json .
RUN npm install --omit=dev
COPY server.js .
RUN mkdir -p /logs
EXPOSE 8002
CMD ["node", "server.js"]
