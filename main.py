"""Servicio astrológico de Caelendar (AGPL-3.0, contenedor propio).

Endpoints puros y sin estado sobre calcular.py. No sabe qué es un usuario:
recibe datos natales y fechas, devuelve posiciones y eventos. Jamás se expone
a internet (puerto interno; en dev se publica 8100 para inspección manual).
"""

from __future__ import annotations

import os
from datetime import date, time

import swisseph as swe
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field, field_validator

import calcular

app = FastAPI(title="Caelendar Motor", version=calcular.ENGINE_VERSION)

swe.set_ephe_path(None)  # Moshier no necesita ruta de efemérides.


class NatalIn(BaseModel):
    birth_date: date
    birth_time: time | None = None
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    birth_tz: str
    time_known: bool = True


class EventosIn(BaseModel):
    natal: NatalIn | None = None
    desde: date
    dias: int = Field(default=30, ge=1, le=120)
    tz: str = "UTC"          # timezone para agrupar la curaduría por día
    solo_globales: bool = False


class EventoContactoIn(BaseModel):
    """Un evento global a medir contra la carta. `clave` la elige el llamador
    (la API manda el uuid del evento) y vuelve intacta en la respuesta."""

    clave: str
    tipo: str
    signo: str
    grado: float | None = None      # los ingresos no lo traen
    cuerpo: str | None = None       # solo ingresos

    @field_validator("signo")
    @classmethod
    def _signo_conocido(cls, v: str) -> str:
        if v not in calcular.SIGNOS:
            raise ValueError(f"signo desconocido: {v}")
        return v


class RevolucionSolarIn(BaseModel):
    natal: NatalIn
    anio: int = Field(ge=1900, le=2200)
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    tz: str = "UTC"           # IANA del lugar; informativo, viaja de vuelta


class ContactosIn(BaseModel):
    natal: NatalIn
    eventos: list[EventoContactoIn] = Field(default_factory=list)


def _natal(datos: NatalIn) -> calcular.Natal:
    return calcular.natal_desde_datos(
        birth_date=datos.birth_date,
        birth_time=datos.birth_time,
        lat=datos.lat,
        lon=datos.lon,
        birth_tz=datos.birth_tz,
        hora_conocida=datos.time_known,
    )


@app.get("/health")
def health() -> dict:
    # `version` es la de la imagen (la del release); `engine_version`, la del
    # cálculo.
    return {"status": "ok", "version": os.environ.get("APP_VERSION", "dev"),
            "engine_version": calcular.ENGINE_VERSION}


@app.post("/natal")
def natal(datos: NatalIn) -> dict:
    chart = calcular.natal_json(_natal(datos))
    return {
        "engine_version": calcular.ENGINE_VERSION,
        "ruleset_version": calcular.RULESET_VERSION,
        "natal": chart,
    }


@app.post("/contactos")
def contactos(datos: ContactosIn) -> dict:
    """Qué toca cada evento global en una carta concreta: casa (Placidus),
    aspectos al grado del evento, puntos natales en su signo y relación con el
    signo solar. Sin estado: la API decide qué guardar."""
    natal_obj = _natal(datos.natal)
    eventos = [ev.model_dump() for ev in datos.eventos]
    return {
        "meta": {
            "engine_version": calcular.ENGINE_VERSION,
            "ruleset_version": calcular.RULESET_VERSION,
        },
        "contactos": calcular.contactos(natal_obj, eventos),
    }


@app.post("/revolucion-solar")
def revolucion_solar(datos: RevolucionSolarIn) -> dict:
    """Instante exacto en que el Sol vuelve a su grado natal en `anio` y la carta
    de ese instante para el lugar, con sus aspectos a la carta natal."""
    try:
        return calcular.revolucion_solar(_natal(datos.natal), datos.anio,
                                         datos.lat, datos.lon, datos.tz)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e


@app.post("/eventos")
def eventos(datos: EventosIn) -> dict:
    natal_obj = _natal(datos.natal) if datos.natal is not None else None
    return calcular.construir_eventos(
        natal=natal_obj,
        desde=datos.desde,
        dias=datos.dias,
        tz=datos.tz,
        solo_globales=datos.solo_globales,
    )
