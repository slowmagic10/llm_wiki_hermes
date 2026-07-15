FROM node:22-alpine AS frontend-builder

WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates git openssh-client wget util-linux \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./requirements.txt
RUN python -m pip install -r requirements.txt
RUN python -m pip install python-multipart==0.0.20 pypdf

COPY *.py ./
COPY --from=frontend-builder /frontend/dist ./web

EXPOSE 18090
CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "18090"]
