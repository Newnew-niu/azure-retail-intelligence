# The web app, built with Node and served by an unprivileged nginx that also proxies /api to the
# API container, so the browser sees one origin and needs no CORS.
FROM node:24-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --ignore-scripts
COPY . .
RUN npm run build

FROM nginxinc/nginx-unprivileged:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 8080
HEALTHCHECK --interval=5s --timeout=3s --start-period=5s --retries=5 \
    CMD ["wget", "--quiet", "--spider", "http://127.0.0.1:8080/"]
