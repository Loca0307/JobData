FROM node:22-alpine

WORKDIR /app

ENV NEXT_TELEMETRY_DISABLED=1

COPY package.json package-lock.json ./
RUN npm ci

COPY . .

ARG NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
ENV NEXT_PUBLIC_API_BASE_URL=${NEXT_PUBLIC_API_BASE_URL}

RUN npm run build
RUN npm prune --omit=dev

ENV NODE_ENV=production \
    HOSTNAME=0.0.0.0 \
    PORT=3000

EXPOSE 3000

CMD ["npm", "start"]
