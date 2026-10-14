"""Tests del servicio HTTP y de las reglas de producto."""

from fastapi.testclient import TestClient

import calcular
from main import app

client = TestClient(app)

LUCIA = {
    "birth_date": "1992-10-03",
    "birth_time": "14:37",
    "lat": 39.4699,
    "lon": -0.3763,
    "birth_tz": "Europe/Madrid",
    "time_known": True,
}


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    assert r.json()["version"] == "dev"          # sin build-arg APP_VERSION


def test_natal_lucia_con_sus_datos_reales():
    """Lucía es una persona de ejemplo (3 oct 1992, 14:37, Valencia): Sol Libra,
    Luna y ASC en Capricornio."""
    r = client.post("/natal", json=LUCIA)
    assert r.status_code == 200
    natal = r.json()["natal"]
    assert natal["planetas"]["sol"]["signo"] == "Libra"
    assert round(natal["planetas"]["sol"]["grado_en_signo"], 1) == 10.6
    assert natal["planetas"]["luna"]["signo"] == "Capricornio"
    assert natal["ascendente"]["signo"] == "Capricornio"


def test_natal_sin_hora_omite_asc_mc():
    datos = {**LUCIA, "birth_time": None, "time_known": False}
    r = client.post("/natal", json=datos)
    natal = r.json()["natal"]
    assert natal["ascendente"] is None
    assert natal["medio_cielo"] is None
    assert natal["hora_conocida"] is False


def test_eventos_personales_sin_hora_excluyen_luna_asc_mc():
    datos = {"natal": {**LUCIA, "birth_time": None, "time_known": False},
             "desde": "2026-08-21", "dias": 30}
    r = client.post("/eventos", json=datos)
    puntos = {ev["payload"]["punto_natal"] for ev in r.json()["eventos_personales"]}
    assert puntos <= {"sol", "venus", "marte"}


def test_eventos_solo_globales():
    r = client.post("/eventos", json={"desde": "2026-08-21", "dias": 45, "solo_globales": True})
    cuerpo = r.json()
    assert cuerpo["eventos_personales"] == []
    tipos = {ev["tipo"] for ev in cuerpo["eventos_globales"]}
    assert "ingreso" in tipos  # siempre hay ingresos en 45 días


def test_eclipse_lunar_de_agosto_2026_en_piscis():
    """Eclipse lunar del 28 de agosto de 2026 en Piscis."""
    r = client.post("/eventos", json={"desde": "2026-08-21", "dias": 10, "solo_globales": True})
    eclipses = [ev for ev in r.json()["eventos_globales"] if ev["tipo"] == "eclipse_lunar"]
    assert len(eclipses) == 1
    assert eclipses[0]["payload"]["signo"] == "Piscis"
    assert eclipses[0]["exacto_utc"].startswith("2026-08-28")


def test_curaduria_maximo_2_aspectos_por_dia():
    eventos = []
    for h in range(5):
        eventos.append({
            "tipo": "aspecto", "familia": "personal", "titulo": f"a{h}",
            "exacto_utc": f"2026-08-21T0{h}:00:00Z", "importancia": 3, "payload": {},
        })
    curados = [ev for ev in calcular.curar(eventos) if ev["tipo"] == "aspecto"]
    assert len(curados) == 2
