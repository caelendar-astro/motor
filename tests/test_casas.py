"""Casas Placidus y Porfirio, y la asignación de casa de una longitud."""

from datetime import date, time

import calcular


def test_sin_hora_no_hay_casas():
    natal = calcular.natal_desde_datos(
        birth_date=date(1992, 10, 3), birth_time=None, lat=39.4699, lon=-0.3763,
        birth_tz="Europe/Madrid", hora_conocida=False)
    chart = calcular.natal_json(natal)
    assert chart["casas"] is None
    assert all(p["casa"] is None for p in chart["planetas"].values())


def test_con_hora_las_cuspides_1_y_10_son_asc_y_mc():
    natal = calcular.natal_desde_datos(
        birth_date=date(1992, 10, 3), birth_time=time(14, 37), lat=39.4699, lon=-0.3763,
        birth_tz="Europe/Madrid", hora_conocida=True)
    chart = calcular.natal_json(natal)
    assert chart["casas"]["sistema"] == "placidus"
    cuspides = chart["casas"]["cuspides"]
    assert len(cuspides) == 12
    assert cuspides[0] == chart["ascendente"]["lon"]
    assert cuspides[9] == chart["medio_cielo"]["lon"]
    assert chart["ascendente"]["casa"] == 1 and chart["medio_cielo"]["casa"] == 10


def test_por_encima_del_circulo_polar_usa_porfirio():
    """Placidus no existe por encima de ~66°: la carta sale igual, con Porfirio."""
    natal = calcular.natal_desde_datos(
        birth_date=date(1990, 6, 1), birth_time=time(12, 0), lat=69.65, lon=18.96,
        birth_tz="Europe/Oslo", hora_conocida=True)
    chart = calcular.natal_json(natal)
    assert chart["casas"]["sistema"] == "porfirio"
    assert all(1 <= p["casa"] <= 12 for p in chart["planetas"].values())


def test_casa_de_cruza_el_cero_de_aries():
    """Una casa que empieza en Piscis y termina en Aries contiene el 0°."""
    cuspides = (350.0, 20.0, 50.0, 80.0, 110.0, 140.0, 170.0, 200.0, 230.0,
                260.0, 290.0, 320.0)
    assert calcular.casa_de(355.0, cuspides) == 1
    assert calcular.casa_de(5.0, cuspides) == 1
    assert calcular.casa_de(20.0, cuspides) == 2
    assert calcular.casa_de(349.9, cuspides) == 12
