# Multi-stage: build the React UI, then run FastAPI serving both API and UI.
FROM node:20-slim AS ui
WORKDIR /ui
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install
COPY frontend/ ./
RUN npm run build

FROM python:3.11-slim AS app
WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY backend/ backend/
# The real data pack is NOT in the repo; it is rehydrated at runtime from a base64 secret
# (see app/core/knowledge.py). Create the dir; sample_data is the built-in fallback.
RUN mkdir -p data
COPY sample_data/ sample_data/
# Built UI goes where main.py looks for it: <project_root>/frontend/dist
COPY --from=ui /ui/dist/ frontend/dist/
ENV PYTHONUNBUFFERED=1
EXPOSE 8000
# $PORT is provided by most PaaS hosts; default to 8000 locally.
CMD ["sh", "-c", "cd backend && uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
