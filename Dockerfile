FROM node:22-bookworm AS frontend
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend ./
RUN npm run build

FROM python:3.11-slim AS runtime
WORKDIR /app
ENV OPEN_NOVEL_HOST=0.0.0.0
ENV OPEN_NOVEL_PORT=8000
ENV OPEN_NOVEL_STATIC_DIR=/app/frontend-dist
COPY pyproject.toml uv.lock README.md ./
COPY open_novel ./open_novel
COPY frontend ./frontend
COPY skills ./skills
COPY scripts ./scripts
COPY --from=frontend /app/frontend/dist ./frontend-dist
RUN pip install --no-cache-dir .
EXPOSE 8000
CMD ["open-novel", "serve", "--host", "0.0.0.0", "--port", "8000"]
