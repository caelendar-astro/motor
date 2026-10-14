# Motor de cálculo astrológico (servicio interno, AGPL).
# python:slim no trae toolchain de C ni base de zonas horarias completa:
# - build-essential: pyswisseph compila desde fuente en arm64 (no hay wheel);
#   gcc solo no alcanza (faltan headers de libc → math.h).
# - tzdata (pip): zoneinfo necesita la base IANA para DST histórico.
FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Versión de la build (la pone el workflow de release). Al final, después del
# código, para no invalidar la caché de las capas de dependencias.
ARG APP_VERSION=dev
ARG GIT_SHA=
ENV APP_VERSION=${APP_VERSION} \
    GIT_SHA=${GIT_SHA}

EXPOSE 8100
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8100"]
