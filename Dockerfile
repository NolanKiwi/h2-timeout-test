# Frontend
FROM node:18-alpine AS frontend-builder
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN npm install
COPY frontend/ ./
RUN npm run build

# Backend + Nginx/Uvicorn (Simplifying: just run backend & serve frontend static if needed, or separate)
# For this project, let's keep it simple:
# - backend container (Python FastAPI)
# - frontend container (Vite dev server or Nginx)

# Let's use docker-compose to orchestrate two containers.
