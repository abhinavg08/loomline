FROM node:22.15.0-slim@sha256:557e52a0fcb928ee113df7e1fb5d4f60c1341dbda53f55e3d815ca10807efdce AS ui
WORKDIR /ui
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/index.html frontend/vite.config.js ./
COPY frontend/src src
RUN npm run build

FROM python:3.12.10-slim@sha256:fd95fa221297a88e1cf49c55ec1828edd7c5a428187e67b5d1805692d11588db
WORKDIR /app
COPY requirements.lock.txt .
RUN pip install --no-cache-dir -r requirements.lock.txt
COPY backend backend
COPY packages/loomline-sdk packages/loomline-sdk
RUN pip install --no-cache-dir --no-deps ./packages/loomline-sdk
COPY scripts scripts
COPY agents agents
COPY examples examples
COPY tests tests
COPY pytest.ini .env.example ./
COPY README.md START_HERE.md ./
COPY docs docs
COPY --from=ui /ui/dist frontend/dist
CMD ["python", "-m", "uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--workers", "1", "--no-access-log"]
