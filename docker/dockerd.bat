@echo off
REM ─── Backend (3-layer build) ───
REM 1. Base image (Python + ODBC，Azure SQL 依赖，勿删)
REM docker build -f docker/Dockerfile-backend.base -t datanexus-python-base:3.11 .
REM 2. Pip image (Python dependencies)
REM docker build -f docker/Dockerfile-backend.pip  -t datanexus-python-pip:3.11 backend
REM 3. App image (application code)
docker build -f docker/Dockerfile-backend      -t datanexus-api backend
docker tag datanexus-api bycontainer.azurecr.io/datanexus-api
docker push bycontainer.azurecr.io/datanexus-api

REM ─── Frontend (ASP.NET + Vue) ───
docker build -t datanexus-server -f docker/Dockerfile-frontend frontend/DataNexus
docker tag datanexus-server bycontainer.azurecr.io/datanexus-server
docker push bycontainer.azurecr.io/datanexus-server
