"""Contactos de un evento global con la carta.

Lucía es una persona de ejemplo (3 oct 1992, 14:37, Valencia). Sus números,
medidos contra el motor:
Sol Libra 10,59 · Luna Capricornio 10,32 · Mercurio Libra 24,04 ·
Venus Escorpio 10,29 · Marte Cáncer 11,35 · Júpiter Virgo 28,51 ·
Saturno Acuario 11,95 · ASC Capricornio 15,06 · MC Escorpio 8,77.

Cúspides Placidus: 1 285,06 · 2 327,20 · 3 7,89 · 4 38,77 · 5 62,43 · 6 83,17 ·
7 105,06 · 8 147,20 · 9 187,89 · 10 218,77 · 11 242,43 · 12 263,17.
"""

from fastapi.testclient import TestClient

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
LUCIA_SIN_HORA = {**LUCIA, "birth_time": None, "time_known": False}


def contactos(natal: dict, eventos: list[dict]) -> list[dict]:
    r = client.post("/contactos", json={"natal": natal, "eventos": eventos})
    assert r.status_code == 200, r.text
    return r.json()["contactos"]


def test_contacto_lunacion_da_casa_y_aspecto_a_venus():
    """Luna nueva en Escorpio 11° (221°), a 0,71° de su Venus natal (Escorpio
    10,29). Cae entre la cúspide 10 (218,77) y la 11 (242,43): casa 10."""
    (c,) = contactos(LUCIA, [{"clave": "e1", "tipo": "luna_nueva",
                              "signo": "Escorpio", "grado": 11.0}])
    assert c["casa"] == 10
    assert c["lon_evento"] == 221.0
    assert {"punto": "venus", "aspecto": "conjunción", "orbe": 0.71} in c["aspectos"]
    # Ordenados por orbe ascendente: ese grado toca cuatro puntos de su carta.
    assert [a["punto"] for a in c["aspectos"]] == ["marte", "luna", "venus", "mc"]
    assert c["planetas_en_signo"] == ["mc", "venus"]


def test_contacto_sin_hora_no_da_casa_ni_luna_asc_mc():
    """Sin hora no hay ASC: ni casa, ni aspectos a Luna/ASC/MC, ni MC en el
    signo. La conjunción con Venus se conserva (los orbes se mueven una décima
    porque la carta sin hora se calcula a mediodía)."""
    (c,) = contactos(LUCIA_SIN_HORA, [{"clave": "e1", "tipo": "luna_nueva",
                                       "signo": "Escorpio", "grado": 11.0}])
    assert c["casa"] is None
    assert {a["punto"] for a in c["aspectos"]} == {"marte", "venus"}
    assert c["planetas_en_signo"] == ["venus"]


def test_contacto_ingreso_lista_planetas_natales_en_el_signo_y_no_aspectos():
    """Un ingreso es un cambio de tono, no un punto: sin grado, sin aspectos.
    En Libra están su Sol (10,59) y su Mercurio (24,04). La casa es la del 15° de
    Libra (195°), donde el cuerpo pasa la mayor parte del tránsito: entre la
    cúspide 9 (187,89) y la 10 (218,77), casa 9. El 0° (180°) caería en la 8."""
    (c,) = contactos(LUCIA, [{"clave": "e1", "tipo": "ingreso",
                              "signo": "Libra", "cuerpo": "mercurio"}])
    assert c["lon_evento"] is None
    assert c["aspectos"] == []
    assert c["planetas_en_signo"] == ["sol", "mercurio"]
    assert c["casa"] == 9


def test_relacion_signo_solar_oposicion():
    """Sol natal en Libra: un evento en Aries cae seis signos enfrente."""
    (c,) = contactos(LUCIA, [{"clave": "e1", "tipo": "luna_llena",
                              "signo": "Aries", "grado": 3.62}])
    assert c["relacion_signo_solar"] == "oposición"
    assert c["aspectos"] == []          # ninguno dentro de 3° (medido)
    assert c["planetas_en_signo"] == []
    assert c["casa"] == 2               # 3,62° (Aries) entre la cúspide 2 y la 3


def test_estacion_de_mercurio_usa_orbe_de_dos_grados():
    """Las estaciones de Mercurio miden con 2°, no con 3°: a 2,5° de su Sol
    natal no hay contacto; la misma posición en una lunación sí lo tendría."""
    evento = {"clave": "e1", "signo": "Libra", "grado": 13.09}   # Sol natal 10,59
    (estacion,) = contactos(LUCIA, [{**evento, "tipo": "mercurio_retro_inicio"}])
    (lunacion,) = contactos(LUCIA, [{**evento, "tipo": "luna_nueva"}])
    assert "sol" not in [a["punto"] for a in estacion["aspectos"]]
    assert {"punto": "sol", "aspecto": "conjunción", "orbe": 2.5} in lunacion["aspectos"]


def test_varios_eventos_vuelven_con_su_clave_y_en_orden():
    salida = contactos(LUCIA, [
        {"clave": "a", "tipo": "ingreso", "signo": "Virgo", "cuerpo": "sol"},
        {"clave": "b", "tipo": "eclipse_lunar", "signo": "Piscis", "grado": 4.85},
    ])
    assert [c["clave"] for c in salida] == ["a", "b"]
    assert salida[0]["planetas_en_signo"] == ["jupiter"]   # Júpiter en Virgo 28,51
    assert salida[1]["casa"] == 2       # 334,85° entre la cúspide 2 (327,20) y la 3
    assert salida[1]["relacion_signo_solar"] == "ninguna"


def test_signo_desconocido_es_422():
    r = client.post("/contactos", json={
        "natal": LUCIA,
        "eventos": [{"clave": "e1", "tipo": "luna_nueva", "signo": "Ofiuco", "grado": 1.0}]})
    assert r.status_code == 422
