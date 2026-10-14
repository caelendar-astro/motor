"""Aspectos entre los puntos de la propia carta.

Lucía es una persona de ejemplo (3 oct 1992, 14:37, Valencia). Sus números,
medidos contra el motor:
Sol Libra 10,59 · Luna Capricornio 10,32 · Mercurio Libra 24,04 ·
Venus Escorpio 10,29 · Marte Cáncer 11,35 · Júpiter Virgo 28,51 ·
Saturno Acuario 11,95 · ASC Capricornio 15,06 · MC Escorpio 8,77.
"""

from datetime import date, time

import calcular

LUCIA = {
    "birth_date": date(1992, 10, 3),
    "birth_time": time(14, 37),
    "lat": 39.4699,
    "lon": -0.3763,
    "birth_tz": "Europe/Madrid",
}


def natal_lucia(hora_conocida: bool = True) -> calcular.Natal:
    return calcular.natal_desde_datos(**LUCIA, hora_conocida=hora_conocida)


def buscar(aspectos: list[dict], a: str, b: str) -> dict | None:
    return next((x for x in aspectos if x["a"] == a and x["b"] == b), None)


def test_lucia_tiene_la_cuadratura_sol_luna_con_orbe_menor_a_medio_grado():
    """Sol 190,59 vs Luna 280,32 → 89,73 de separación: cuadratura de 0,27."""
    a = calcular.aspectos_natales(natal_lucia())
    sol_luna = buscar(a, "sol", "luna")
    assert sol_luna == {"a": "sol", "b": "luna", "aspecto": "cuadratura", "orbe": 0.27}


def test_los_aspectos_salen_ordenados_por_orbe_ascendente():
    a = calcular.aspectos_natales(natal_lucia())
    assert [x["orbe"] for x in a] == sorted(x["orbe"] for x in a)
    # El más cerrado de su carta es el sextil Luna-Venus (280,32 vs 220,29).
    assert a[0] == {"a": "luna", "b": "venus", "aspecto": "sextil", "orbe": 0.03}


def test_lucia_tiene_oposicion_luna_marte_y_trigono_venus_marte():
    """La T-cuadrada Sol/Luna/Marte y el trígono de agua Venus-Marte."""
    a = calcular.aspectos_natales(natal_lucia())
    assert buscar(a, "luna", "marte") == {
        "a": "luna", "b": "marte", "aspecto": "oposición", "orbe": 1.02}
    assert buscar(a, "venus", "marte") == {
        "a": "venus", "b": "marte", "aspecto": "trígono", "orbe": 1.05}
    assert buscar(a, "sol", "marte")["aspecto"] == "cuadratura"


def test_lucia_tiene_conjuncion_mc_venus_dentro_del_orbe_de_angulo():
    """MC 218,77 vs Venus 220,29: 1,52, por debajo de los 4° de un ángulo."""
    a = calcular.aspectos_natales(natal_lucia())
    assert buscar(a, "venus", "mc") == {
        "a": "venus", "b": "mc", "aspecto": "conjunción", "orbe": 1.53}


def test_no_hay_par_asc_mc():
    a = calcular.aspectos_natales(natal_lucia())
    assert buscar(a, "asc", "mc") is None
    assert buscar(a, "mc", "asc") is None


def test_un_par_produce_como_mucho_un_aspecto():
    a = calcular.aspectos_natales(natal_lucia())
    pares = [(x["a"], x["b"]) for x in a]
    assert len(pares) == len(set(pares))


def test_sin_hora_no_hay_aspectos_con_asc_ni_mc_pero_si_con_luna():
    a = calcular.aspectos_natales(natal_lucia(hora_conocida=False))
    assert not [x for x in a if "asc" in (x["a"], x["b"]) or "mc" in (x["a"], x["b"])]
    assert [x for x in a if "luna" in (x["a"], x["b"])]


def test_orbe_de_angulo_es_cuatro():
    """Un planeta a 5° del ASC no aspecta; a 3,9°, sí."""
    natal = natal_lucia()
    for distancia, esperado in ((5.0, False), (3.9, True)):
        sintetico = calcular.Natal(
            jd=natal.jd,
            posiciones={**natal.posiciones,
                        "jupiter": {**natal.posiciones["jupiter"],
                                    "lon": (natal.asc + distancia) % 360}},
            asc=natal.asc, mc=natal.mc, hora_conocida=True)
        a = calcular.aspectos_natales(sintetico)
        assert (buscar(a, "jupiter", "asc") is not None) is esperado


def test_natal_json_incluye_los_aspectos():
    salida = calcular.natal_json(natal_lucia())
    assert salida["aspectos"] == calcular.aspectos_natales(natal_lucia())


def test_engine_version_es_cero_seis_cero_y_el_ruleset_no_sube():
    """0.6.0: revolución solar (0.5.0: conjunciones y oposiciones; 0.4.0: Placidus).
    El ruleset no sube: ningún evento emitido cambia."""
    assert calcular.ENGINE_VERSION == "0.6.0"
    assert calcular.RULESET_VERSION == "mvp-2"
