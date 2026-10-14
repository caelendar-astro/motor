"""Revolución solar: instante exacto + carta para un lugar."""

from datetime import date, time

from fastapi.testclient import TestClient

import calcular
from main import app

client = TestClient(app)

BARCELONA = (41.3874, 2.1686)
MADRID = (40.4168, -3.7038)


def natal_lucia() -> calcular.Natal:
    """Persona de ejemplo: 3 oct 1992, 14:37, Valencia."""
    return calcular.natal_desde_datos(date(1992, 10, 3), time(14, 37), 39.4699, -0.3763,
                                      "Europe/Madrid", hora_conocida=True)


def test_el_sol_vuelve_a_su_grado_natal_el_dia_del_cumpleanios():
    natal = natal_lucia()
    rs = calcular.revolucion_solar(natal, 2026, *BARCELONA)
    # Fijado contra el motor: 3 oct 2026, 21:14 en Barcelona.
    assert rs["exacto_utc"] == "2026-10-03T19:14:25Z"
    assert abs(rs["carta"]["planetas"]["sol"]["lon"] - natal.posiciones["sol"]["lon"]) < 0.0001


def test_el_lugar_cambia_las_casas_pero_no_el_instante():
    natal = natal_lucia()
    barcelona = calcular.revolucion_solar(natal, 2026, *BARCELONA)
    madrid = calcular.revolucion_solar(natal, 2026, *MADRID)
    assert barcelona["exacto_utc"] == madrid["exacto_utc"]
    assert barcelona["carta"]["ascendente"]["lon"] != madrid["carta"]["ascendente"]["lon"]
    assert barcelona["carta"]["casas"]["cuspides"] != madrid["carta"]["casas"]["cuspides"]


def test_sin_hora_no_hay_casas_ni_angulos_en_la_rs():
    natal = calcular.natal_desde_datos(date(1992, 10, 3), None, 39.4699, -0.3763,
                                       "Europe/Madrid", hora_conocida=False)
    rs = calcular.revolucion_solar(natal, 2026, *MADRID)
    carta = rs["carta"]
    assert carta["hora_conocida"] is False
    assert carta["ascendente"] is None and carta["medio_cielo"] is None
    assert carta["casas"] is None
    assert all(p["casa"] is None for p in carta["planetas"].values())
    assert not any("asc" in (a["rs"], a["natal"]) or "mc" in (a["rs"], a["natal"])
                   for a in rs["aspectos_con_natal"])


def test_aspectos_con_natal_incluye_la_conjuncion_sol_sol_con_orbe_cero():
    rs = calcular.revolucion_solar(natal_lucia(), 2026, *BARCELONA)
    primero = rs["aspectos_con_natal"][0]
    assert primero == {"rs": "sol", "natal": "sol", "aspecto": "conjunción", "orbe": 0.0}
    orbes = [a["orbe"] for a in rs["aspectos_con_natal"]]
    assert orbes == sorted(orbes)
    pares = [(a["rs"], a["natal"]) for a in rs["aspectos_con_natal"]]
    assert len(pares) == len(set(pares))


def test_veintinueve_de_febrero_cae_en_veintiocho():
    natal = calcular.natal_desde_datos(date(1980, 2, 29), None, 40.4, -3.7,
                                       "Europe/Madrid", hora_conocida=False)
    rs = calcular.revolucion_solar(natal, 2026, *MADRID)
    assert rs["exacto_utc"].startswith("2026-02-28")


def test_el_endpoint_devuelve_la_rs_con_el_lugar():
    r = client.post("/revolucion-solar", json={
        "natal": {"birth_date": "1992-10-03", "birth_time": "14:37", "lat": 39.4699,
                  "lon": -0.3763, "birth_tz": "Europe/Madrid", "time_known": True},
        "anio": 2026, "lat": MADRID[0], "lon": MADRID[1], "tz": "Europe/Madrid",
    })
    assert r.status_code == 200
    cuerpo = r.json()
    assert cuerpo["engine_version"] == "0.6.0"
    assert cuerpo["anio"] == 2026
    assert cuerpo["exacto_utc"].startswith("2026-10-03")
    assert cuerpo["lugar"] == {"lat": MADRID[0], "lon": MADRID[1], "tz": "Europe/Madrid"}
    assert cuerpo["carta"]["casas"]["sistema"] == "placidus"
    assert cuerpo["aspectos_con_natal"][0]["rs"] == "sol"
