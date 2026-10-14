"""Núcleo de cálculo astrológico de Caelendar.

Produce, en JSON canónico:
  1. Carta natal: Sol, Mercurio, Venus, Marte, Júpiter, Saturno, Luna + ASC + MC,
     con los aspectos mayores entre esos puntos (lo que la rueda dibuja).
  2. Eventos GLOBALES de una ventana: lunaciones, estaciones de Mercurio,
     ingresos de Sol/Mercurio/Venus/Marte y eclipses.
  3. Eventos PERSONALES: aspectos mayores tránsito→natal, con instante exacto
     (UTC), ventana de influencia, importancia (1-5) y marca de retorno.
  4. Revolución solar: el instante en que el Sol vuelve a su grado natal en un
     año dado y la carta de ese instante para un lugar.

Decisiones (ver README.md):
- Efemérides Moshier (FLG_MOSEPH): integradas en pyswisseph, sin archivos .se1.
- Instantes exactos por muestreo + bisección sobre la función de cruce.
- La Luna NO transita; Luna/ASC/MC receptores solo con hora conocida.
- Curaduría de densidad: máx 6 eventos/día y máx 2 aspectos/día,
  agrupando por día en el timezone que pida el llamador.
- Casas Placidus (el estándar de la astrología occidental moderna);
  Porfirio por encima del círculo polar, donde Placidus no está definido.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import swisseph as swe

ENGINE_VERSION = "0.6.0"
RULESET_VERSION = "mvp-2"

# Efemérides Moshier (sin archivos externos) + velocidades (retrógrados/estaciones).
FLAGS = swe.FLG_MOSEPH | swe.FLG_SPEED

PLANETS = {
    "sol": swe.SUN,
    "luna": swe.MOON,
    "mercurio": swe.MERCURY,
    "venus": swe.VENUS,
    "marte": swe.MARS,
    "jupiter": swe.JUPITER,
    "saturno": swe.SATURN,
}

SIGNOS = [
    "Aries", "Tauro", "Géminis", "Cáncer", "Leo", "Virgo",
    "Libra", "Escorpio", "Sagitario", "Capricornio", "Acuario", "Piscis",
]

# Sistema de casas. Placidus es el estándar de la astrología occidental moderna.
# Por encima de ~66° de latitud Placidus no existe (hay grados de la eclíptica que
# no salen ni se ponen): ahí se usa Porfirio, que reparte los cuadrantes en tres.
SISTEMA_CASAS = b"P"
SISTEMA_CASAS_POLAR = b"O"
LATITUD_POLAR = 66.0

# Aspectos mayores.
ASPECTOS = {0: "conjunción", 60: "sextil", 90: "cuadratura", 120: "trígono", 180: "oposición"}

# Orbe por cuerpo en TRÁNSITO (grados).
ORBE_POR_CUERPO = {
    "sol": 2.0, "luna": 2.0,
    "mercurio": 1.0, "venus": 1.0, "marte": 1.0,
    "jupiter": 1.5, "saturno": 1.5,
}

CUERPOS_TRANSITO = ["sol", "mercurio", "venus", "marte", "jupiter", "saturno"]

PUNTOS_NATALES_BASE = ["sol", "venus", "marte"]
PUNTOS_NATALES_HORA = ["luna", "asc", "mc"]

# Importancia (1-5) de cada evento: decide qué se conserva en un día cargado.
IMPORTANCIA_GLOBAL = {
    "luna_nueva": 4, "luna_llena": 4,
    "mercurio_retro_inicio": 3, "mercurio_retro_fin": 3,
    "eclipse_solar": 5, "eclipse_lunar": 5,
}

MAX_EVENTOS_DIA = 6
MAX_ASPECTOS_DIA = 2

# --- Contactos de un evento global con la carta ---------------------------------
# Orbe del contacto según el tipo de evento. Los ingresos no tienen grado: no
# entran en esta tabla porque no producen aspectos.
ORBE_CONTACTO = {
    "luna_nueva": 3.0, "luna_llena": 3.0,
    "eclipse_solar": 3.0, "eclipse_lunar": 3.0,
    "mercurio_retro_inicio": 2.0, "mercurio_retro_fin": 2.0,
}

# Orden fijo de los puntos natales en `planetas_en_signo`.
ORDEN_PUNTOS = ["sol", "luna", "asc", "mc", "mercurio", "venus", "marte",
                "jupiter", "saturno"]

# --- Aspectos entre puntos de la propia carta -----------------------------------
# Orden canónico de los puntos natales en un aspecto: `a` siempre antes que `b`.
ORDEN_PUNTOS_NATAL = ["sol", "luna", "mercurio", "venus", "marte", "jupiter",
                      "saturno", "asc", "mc"]

# Orbe máximo por aspecto entre puntos natales (12 §1 decisión 7). Más generoso
# que el de un tránsito: acá no hay instante exacto, hay una figura fija.
ORBE_NATAL = {"conjunción": 7.0, "oposición": 7.0, "cuadratura": 6.0,
              "trígono": 6.0, "sextil": 4.0}

# Con un ángulo (ASC/MC) de por medio el orbe se cierra: dependen de la hora, y
# un error de minutos los mueve más que a cualquier planeta.
ORBE_NATAL_ANGULO = 4.0

# Puntos que cuentan como dato de SIGNO pero no reciben aspectos por grado:
# «Mercurio entra en el signo de tu Mercurio» es información, y no depende del orbe.
PUNTOS_SOLO_SIGNO = ["mercurio", "jupiter", "saturno"]

# Distancia en signos (evento − Sol natal) → relación. Lo que no está: "ninguna".
RELACION_SIGNO_SOLAR = {
    0: "mismo", 6: "oposición", 3: "cuadratura", 9: "cuadratura",
    4: "trígono", 8: "trígono", 2: "sextil", 10: "sextil",
}


# --------------------------------------------------------------------------- #
# Utilidades de tiempo y ángulos
# --------------------------------------------------------------------------- #

def jd_from_dt(dt_utc: datetime) -> float:
    dt = dt_utc.astimezone(timezone.utc)
    frac = dt.hour + dt.minute / 60 + dt.second / 3600 + dt.microsecond / 3.6e9
    return swe.julday(dt.year, dt.month, dt.day, frac, swe.GREG_CAL)


def dt_from_jd(jd: float) -> datetime:
    y, mo, d, frac = swe.revjul(jd, swe.GREG_CAL)
    h = int(frac)
    m = int((frac - h) * 60)
    s = int(round((((frac - h) * 60) - m) * 60))
    base = datetime(y, mo, d, h, m, 0, tzinfo=timezone.utc)
    return base + timedelta(seconds=s)


def iso(jd: float) -> str:
    return dt_from_jd(jd).strftime("%Y-%m-%dT%H:%M:%SZ")


def norm_diff(x: float) -> float:
    """Diferencia angular normalizada a (-180, 180]."""
    return ((x + 180) % 360) - 180


def separacion(a: float, b: float) -> float:
    """Separación angular absoluta en [0, 180]."""
    return abs(norm_diff(a - b))


def signo_de(lon: float) -> tuple[str, float]:
    idx = int(lon // 30) % 12
    return SIGNOS[idx], lon % 30


def bisectar(f, t0: float, t1: float, iters: int = 60) -> float:
    """Raíz de f en [t0, t1] (Julian Day) asumiendo cambio de signo."""
    f0 = f(t0)
    for _ in range(iters):
        tm = (t0 + t1) / 2
        fm = f(tm)
        if fm == 0:
            return tm
        if (f0 < 0) != (fm < 0):
            t1 = tm
        else:
            t0, f0 = tm, fm
    return (t0 + t1) / 2


def lon_de(jd: float, planeta: int) -> float:
    pos, _ = swe.calc_ut(jd, planeta, FLAGS)
    return pos[0]


def velocidad_de(jd: float, planeta: int) -> float:
    pos, _ = swe.calc_ut(jd, planeta, FLAGS)
    return pos[3]


# --------------------------------------------------------------------------- #
# Carta natal
# --------------------------------------------------------------------------- #

@dataclass
class Natal:
    jd: float
    posiciones: dict
    asc: float
    mc: float
    hora_conocida: bool
    # Las 12 cúspides (casa 1 = ASC, casa 10 = MC) y el sistema con que salieron.
    cuspides: tuple[float, ...] = ()
    sistema_casas: str = "placidus"


def casa_de(lon: float, cuspides: tuple[float, ...]) -> int:
    """Casa (1-12) de una longitud: la que va de su cúspide a la siguiente, en
    sentido zodiacal. Las casas de Placidus no miden 30°: no sale del signo."""
    for i in range(12):
        inicio = cuspides[i]
        fin = cuspides[(i + 1) % 12]
        if (lon - inicio) % 360 < (fin - inicio) % 360:
            return i + 1
    return 12  # inalcanzable: las doce cúspides cubren el círculo


def natal_desde_datos(
    birth_date: date,
    birth_time: time | None,
    lat: float,
    lon: float,
    birth_tz: str,
    hora_conocida: bool,
) -> Natal:
    """Hora desconocida → mediodía local."""
    hora = birth_time if (hora_conocida and birth_time is not None) else time(12, 0)
    tz = ZoneInfo(birth_tz)
    dt_local = datetime.combine(birth_date, hora, tzinfo=tz)
    dt_utc = dt_local.astimezone(timezone.utc)
    return calcular_natal(dt_utc, lat, lon, hora_conocida)


def calcular_natal(dt_utc: datetime, lat: float, lon: float, hora_conocida: bool) -> Natal:
    jd = jd_from_dt(dt_utc)
    posiciones = {}
    for nombre, planeta in PLANETS.items():
        pos, _ = swe.calc_ut(jd, planeta, FLAGS)
        s, g = signo_de(pos[0])
        posiciones[nombre] = {
            "lon": round(pos[0], 6),
            "signo": s,
            "grado_en_signo": round(g, 4),
            "velocidad": round(pos[3], 6),
            "retrogrado": pos[3] < 0,
        }
    polar = abs(lat) >= LATITUD_POLAR
    cuspides, ascmc = swe.houses_ex(
        jd, lat, lon, SISTEMA_CASAS_POLAR if polar else SISTEMA_CASAS, FLAGS)
    return Natal(jd=jd, posiciones=posiciones, asc=ascmc[0], mc=ascmc[1],
                 hora_conocida=hora_conocida, cuspides=tuple(cuspides[:12]),
                 sistema_casas="porfirio" if polar else "placidus")


def natal_json(natal: Natal) -> dict:
    """Sin hora no hay casas: `casas` es null y ningún punto lleva `casa`."""
    planetas = {}
    for nombre, datos in natal.posiciones.items():
        casa = casa_de(datos["lon"], natal.cuspides) if natal.hora_conocida else None
        planetas[nombre] = {**datos, "casa": casa}
    out = {
        "hora_conocida": natal.hora_conocida,
        "planetas": planetas,
    }
    if natal.hora_conocida:
        for nombre, val, casa in (("ascendente", natal.asc, 1), ("medio_cielo", natal.mc, 10)):
            s, g = signo_de(val)
            out[nombre] = {"lon": round(val, 6), "signo": s, "grado_en_signo": round(g, 4),
                           "casa": casa}
        out["casas"] = {"sistema": natal.sistema_casas,
                        "cuspides": [round(c, 6) for c in natal.cuspides]}
    else:
        out["ascendente"] = None
        out["medio_cielo"] = None
        out["casas"] = None
    out["aspectos"] = aspectos_natales(natal)
    return out


# --------------------------------------------------------------------------- #
# Eventos globales
# --------------------------------------------------------------------------- #

def lunaciones(jd_ini: float, dias: int, paso_h: float = 6.0) -> list[dict]:
    n = int(dias * 24 / paso_h)
    grid = [jd_ini + k * paso_h / 24 for k in range(n + 1)]
    elong = [norm_diff(lon_de(t, swe.MOON) - lon_de(t, swe.SUN)) for t in grid]
    eventos = []
    for objetivo, tipo, titulo in [(0.0, "luna_nueva", "Luna nueva"),
                                   (180.0, "luna_llena", "Luna llena")]:
        f = lambda t, o=objetivo: norm_diff((lon_de(t, swe.MOON) - lon_de(t, swe.SUN)) - o)
        for i in range(n):
            a, b = (norm_diff(elong[i] - objetivo), norm_diff(elong[i + 1] - objetivo))
            if (a < 0) != (b < 0) and abs(a) < 90 and abs(b) < 90:
                jd = bisectar(f, grid[i], grid[i + 1])
                s, g = signo_de(lon_de(jd, swe.MOON))
                eventos.append({
                    "tipo": tipo, "familia": "global", "titulo": f"{titulo} en {s}",
                    "exacto_utc": iso(jd), "importancia": IMPORTANCIA_GLOBAL[tipo],
                    "payload": {"signo": s, "grado": round(g, 2)},
                })
    return eventos


def estaciones_mercurio(jd_ini: float, dias: int, paso_h: float = 12.0) -> list[dict]:
    n = int(dias * 24 / paso_h)
    grid = [jd_ini + k * paso_h / 24 for k in range(n + 1)]
    vel = [velocidad_de(t, swe.MERCURY) for t in grid]
    f = lambda t: velocidad_de(t, swe.MERCURY)
    eventos = []
    for i in range(n):
        if (vel[i] < 0) != (vel[i + 1] < 0):
            jd = bisectar(f, grid[i], grid[i + 1])
            retro = vel[i + 1] < 0
            tipo = "mercurio_retro_inicio" if retro else "mercurio_retro_fin"
            titulo = "Mercurio se vuelve retrógrado" if retro else "Mercurio se vuelve directo"
            s, g = signo_de(lon_de(jd, swe.MERCURY))
            eventos.append({
                "tipo": tipo, "familia": "global", "titulo": titulo,
                "exacto_utc": iso(jd), "importancia": IMPORTANCIA_GLOBAL[tipo],
                "payload": {"signo": s, "grado": round(g, 2)},
            })
    return eventos


def ingresos(jd_ini: float, dias: int, paso_h: float = 6.0) -> list[dict]:
    eventos = []
    for nombre in ["sol", "mercurio", "venus", "marte"]:
        planeta = PLANETS[nombre]
        n = int(dias * 24 / paso_h)
        grid = [jd_ini + k * paso_h / 24 for k in range(n + 1)]
        lons = [lon_de(t, planeta) for t in grid]
        for i in range(n):
            s0 = int(lons[i] // 30) % 12
            s1 = int(lons[i + 1] // 30) % 12
            if s0 == s1:
                continue
            # Múltiplo de 30 más cercano al punto medio = límite cruzado (robusto al wrap).
            mid = lons[i] + norm_diff(lons[i + 1] - lons[i]) / 2
            borde = (30 * round(mid / 30)) % 360
            f = lambda t, b=borde: norm_diff(lon_de(t, planeta) - b)
            jd = bisectar(f, grid[i], grid[i + 1])
            s_post, _ = signo_de(lon_de(jd + 0.01, planeta))
            importancia = 2 if nombre == "sol" else 1
            eventos.append({
                "tipo": "ingreso", "familia": "global",
                "titulo": f"{nombre.capitalize()} entra en {s_post}",
                "exacto_utc": iso(jd), "importancia": importancia,
                "payload": {"cuerpo": nombre, "signo": s_post},
            })
    return eventos


def eclipses(jd_ini: float, dias: int) -> list[dict]:
    """Todos los eclipses de la ventana (bucle sobre los buscadores dedicados)."""
    eventos = []
    jd_fin = jd_ini + dias
    for buscador, tipo, titulo, cuerpo in (
        (swe.sol_eclipse_when_glob, "eclipse_solar", "Eclipse solar", swe.SUN),
        (swe.lun_eclipse_when, "eclipse_lunar", "Eclipse lunar", swe.MOON),
    ):
        jd = jd_ini
        while True:
            ret, tret = buscador(jd, FLAGS, 0, False)
            if tret[0] > jd_fin:
                break
            s, g = signo_de(lon_de(tret[0], cuerpo))
            eventos.append({
                "tipo": tipo, "familia": "global", "titulo": f"{titulo} en {s}",
                "exacto_utc": iso(tret[0]), "importancia": IMPORTANCIA_GLOBAL[tipo],
                "payload": {"signo": s, "grado": round(g, 2), "swe_retflag": int(ret)},
            })
            jd = tret[0] + 1.0
    return eventos


def eventos_globales(jd_ini: float, dias: int) -> list[dict]:
    lunas = lunaciones(jd_ini, dias)
    ecl = eclipses(jd_ini, dias)
    # Un eclipse ES una lunación: se queda solo el eclipse, o el calendario mostraría
    # dos cards para el mismo instante del cielo.
    dias_eclipse = {ev["exacto_utc"][:10] for ev in ecl}
    lunas = [ev for ev in lunas if ev["exacto_utc"][:10] not in dias_eclipse]

    out = lunas + estaciones_mercurio(jd_ini, dias) + ingresos(jd_ini, dias) + ecl
    out.sort(key=lambda ev: ev.get("exacto_utc", ""))
    return out


# --------------------------------------------------------------------------- #
# Eventos personales (aspectos tránsito → natal)
# --------------------------------------------------------------------------- #

def _puntos_natales(natal: Natal) -> dict:
    puntos = {n: natal.posiciones[n]["lon"] for n in PUNTOS_NATALES_BASE}
    if natal.hora_conocida:
        puntos["luna"] = natal.posiciones["luna"]["lon"]
        puntos["asc"] = natal.asc
        puntos["mc"] = natal.mc
    return puntos


def _importancia_personal(cuerpo: str, punto: str, aspecto: str, es_retorno: bool) -> int:
    if es_retorno and cuerpo == "sol":
        return 5  # la vuelta al Sol: el cumpleaños astrológico, protagonista de su día
    if es_retorno and cuerpo in ("venus", "marte"):
        return 4
    if cuerpo in ("jupiter", "saturno"):
        return 4
    if aspecto in ("conjunción", "oposición") and punto in ("sol", "luna", "asc"):
        return 4
    return 3


def aspectos_personales(natal: Natal, jd_ini: float, dias: int, paso_h: float = 6.0) -> list[dict]:
    n = int(dias * 24 / paso_h)
    grid = [jd_ini + k * paso_h / 24 for k in range(n + 1)]
    lon_grid = {c: [lon_de(t, PLANETS[c]) for t in grid] for c in CUERPOS_TRANSITO}
    puntos = _puntos_natales(natal)
    eventos = []

    for cuerpo in CUERPOS_TRANSITO:
        orbe = ORBE_POR_CUERPO[cuerpo]
        lons = lon_grid[cuerpo]
        for punto_nombre, punto_lon in puntos.items():
            for ang, asp_nombre in ASPECTOS.items():
                # La separación absoluta ([0, 180]) toca el 0° o el 180° y rebota sin
                # cambiar de signo: con ella las conjunciones (y por tanto los retornos)
                # y las oposiciones no se detectaban nunca. Para esos dos ángulos se usa
                # la diferencia con signo; su salto en ±180° no es un cruce real y se
                # descarta porque ahí los dos valores son grandes.
                if ang in (0, 180):
                    g = lambda L, pl=punto_lon, a=ang: norm_diff(L - pl - a)
                else:
                    g = lambda L, pl=punto_lon, a=ang: separacion(L, pl) - a
                e = [g(L) for L in lons]
                f = lambda t, c=PLANETS[cuerpo], g=g: g(lon_de(t, c))
                vistos = set()
                for i in range(n):
                    cruce = (e[i] == 0) or ((e[i] < 0) != (e[i + 1] < 0))
                    if not cruce or (abs(e[i]) > 90 and abs(e[i + 1]) > 90):
                        continue
                    jd_exact = bisectar(f, grid[i], grid[i + 1]) if e[i] != 0 else grid[i]
                    clave = round(jd_exact, 3)
                    if clave in vistos:
                        continue
                    vistos.add(clave)
                    ventana = _ventana_influencia(f, grid, e, i, orbe, jd_exact)
                    es_retorno = (asp_nombre == "conjunción" and cuerpo == punto_nombre)
                    lon_transito = lon_de(jd_exact, PLANETS[cuerpo])
                    s_transito, g_transito = signo_de(lon_transito)
                    s_natal, g_natal = signo_de(punto_lon)
                    retro = velocidad_de(jd_exact, PLANETS[cuerpo]) < 0
                    eventos.append({
                        "tipo": "aspecto", "familia": "personal",
                        "titulo": f"{cuerpo.capitalize()} {asp_nombre} {punto_nombre.capitalize()} natal",
                        "exacto_utc": iso(jd_exact),
                        "importancia": _importancia_personal(cuerpo, punto_nombre, asp_nombre, es_retorno),
                        "payload": {
                            "transito": cuerpo, "punto_natal": punto_nombre,
                            "aspecto": asp_nombre, "angulo": ang, "orbe": orbe,
                            "es_retorno": es_retorno, "retro": retro,
                            "signo_transito": s_transito, "grado_transito": round(g_transito, 2),
                            "signo_natal": s_natal, "grado_natal": round(g_natal, 2),
                            "ventana_inicio_utc": ventana[0], "ventana_fin_utc": ventana[1],
                        },
                    })
    eventos.sort(key=lambda ev: ev["exacto_utc"])
    return eventos


def _ventana_influencia(f, grid, e, i_exact, orbe, jd_exact):
    """Ventana donde |separación - ángulo| <= orbe. Bordes por bisección."""
    n = len(grid) - 1
    lo = i_exact
    while lo > 0 and abs(e[lo]) <= orbe:
        lo -= 1
    hi = min(i_exact + 1, n)
    while hi < n and abs(e[hi]) <= orbe:
        hi += 1

    inicio = grid[0]
    if abs(e[lo]) > orbe:
        signo_borde = orbe if e[lo] > 0 else -orbe
        g = lambda t, sb=signo_borde: f(t) - sb
        inicio = bisectar(g, grid[lo], grid[lo + 1])
    fin = grid[n]
    if abs(e[hi]) > orbe:
        signo_borde = orbe if e[hi] > 0 else -orbe
        g = lambda t, sb=signo_borde: f(t) - sb
        fin = bisectar(g, grid[hi - 1], grid[hi])
    return iso(inicio), iso(fin)


# --------------------------------------------------------------------------- #
# Aspectos de la carta consigo misma
# --------------------------------------------------------------------------- #

def _puntos_natal_completos(natal: Natal) -> dict:
    """Los puntos que entran en un aspecto natal: los 7 cuerpos siempre, ASC y MC
    solo con hora. La Luna entra aunque no haya hora (es la carta, no un
    tránsito: su grado es aproximado y así lo dice la pantalla)."""
    puntos = {n: natal.posiciones[n]["lon"] for n in PLANETS}
    if natal.hora_conocida:
        puntos["asc"] = natal.asc
        puntos["mc"] = natal.mc
    return puntos


def aspectos_natales(natal: Natal) -> list[dict]:
    """Aspectos mayores entre los puntos de la propia carta, ordenados por orbe.

    Un par produce como mucho un aspecto (el de menor orbe). El par ASC-MC nunca
    aspecta: su ángulo es geometría del lugar y la hora, no una relación de la
    carta.
    """
    puntos = _puntos_natal_completos(natal)
    presentes = [n for n in ORDEN_PUNTOS_NATAL if n in puntos]
    salida: list[dict] = []

    for i, a in enumerate(presentes):
        for b in presentes[i + 1:]:
            if {a, b} == {"asc", "mc"}:
                continue
            angulo = separacion(puntos[a], puntos[b])
            es_angulo = a in ("asc", "mc") or b in ("asc", "mc")
            mejor: tuple[float, str] | None = None
            for exacto, nombre in ASPECTOS.items():
                orbe = abs(angulo - exacto)
                maximo = ORBE_NATAL_ANGULO if es_angulo else ORBE_NATAL[nombre]
                if orbe <= maximo and (mejor is None or orbe < mejor[0]):
                    mejor = (orbe, nombre)
            if mejor is not None:
                salida.append({"a": a, "b": b, "aspecto": mejor[1],
                               "orbe": round(mejor[0], 2)})

    salida.sort(key=lambda d: (d["orbe"], ORDEN_PUNTOS_NATAL.index(d["a"]),
                               ORDEN_PUNTOS_NATAL.index(d["b"])))
    return salida


# --------------------------------------------------------------------------- #
# Revolución solar
# --------------------------------------------------------------------------- #

def _puntos_con_angulos(carta: Natal) -> dict:
    """Los 7 cuerpos y, con hora, ASC y MC: los puntos de una carta que aspectan."""
    return _puntos_natal_completos(carta)


def aspectos_entre(rs: Natal, natal: Natal) -> list[dict]:
    """Aspectos mayores de cada punto de la RS a cada punto natal, por orbe.

    Mismos orbes que los aspectos natales (4° si interviene un ángulo de cualquiera
    de las dos cartas). Un par produce como mucho un aspecto: el de menor orbe. El
    par Sol RS – Sol natal (conjunción, orbe 0) es la definición de la RS y entra.
    """
    puntos_rs = _puntos_con_angulos(rs)
    puntos_natal = _puntos_con_angulos(natal)
    salida: list[dict] = []
    for a in ORDEN_PUNTOS_NATAL:
        if a not in puntos_rs:
            continue
        for b in ORDEN_PUNTOS_NATAL:
            if b not in puntos_natal:
                continue
            angulo = separacion(puntos_rs[a], puntos_natal[b])
            es_angulo = a in ("asc", "mc") or b in ("asc", "mc")
            mejor: tuple[float, str] | None = None
            for exacto, nombre in ASPECTOS.items():
                orbe = abs(angulo - exacto)
                maximo = ORBE_NATAL_ANGULO if es_angulo else ORBE_NATAL[nombre]
                if orbe <= maximo and (mejor is None or orbe < mejor[0]):
                    mejor = (orbe, nombre)
            if mejor is not None:
                salida.append({"rs": a, "natal": b, "aspecto": mejor[1],
                               "orbe": round(mejor[0], 2)})
    salida.sort(key=lambda d: (d["orbe"], ORDEN_PUNTOS_NATAL.index(d["rs"]),
                               ORDEN_PUNTOS_NATAL.index(d["natal"])))
    return salida


def instante_revolucion_solar(natal: Natal, anio: int) -> float:
    """Julian Day del instante en que el Sol vuelve a su longitud natal en `anio`.

    Ventana: cumpleaños civil (en UTC) −2 días durante 5 días, paso 6 h. El Sol
    avanza ~1°/día y nunca retrograda, así que dentro de la ventana hay una sola
    raíz. Un 29 de febrero busca desde el 28 en los años no bisiestos.
    """
    L0 = natal.posiciones["sol"]["lon"]
    nacimiento = dt_from_jd(natal.jd)
    try:
        cumple = nacimiento.replace(year=anio)
    except ValueError:  # 29 de febrero en año no bisiesto
        cumple = nacimiento.replace(year=anio, day=28)
    inicio = jd_from_dt(cumple - timedelta(days=2))
    pasos = int(5 * 24 / 6)
    grid = [inicio + k * 6 / 24 for k in range(pasos + 1)]
    f = lambda t: norm_diff(lon_de(t, swe.SUN) - L0)
    e = [f(t) for t in grid]
    raices = []
    for i in range(pasos):
        if e[i] == 0:
            raices.append(grid[i])
        elif (e[i] < 0) != (e[i + 1] < 0) and abs(e[i]) < 90 and abs(e[i + 1]) < 90:
            raices.append(bisectar(f, grid[i], grid[i + 1]))
    if len(raices) != 1:
        raise ValueError(f"revolución solar {anio}: {len(raices)} raíces en la ventana")
    return raices[0]


def revolucion_solar(natal: Natal, anio: int, lat: float, lon: float, tz: str = "UTC") -> dict:
    """La revolución solar de `anio` levantada para (lat, lon).

    El lugar no mueve el instante (es el Sol volviendo a su grado): solo cambia
    las casas y los ángulos. Sin hora natal la carta va sin casas ni ASC/MC.
    """
    jd = instante_revolucion_solar(natal, anio)
    dt_utc = dt_from_jd(jd)
    rs = calcular_natal(dt_utc, lat, lon, natal.hora_conocida)
    return {
        "engine_version": ENGINE_VERSION,
        "ruleset_version": RULESET_VERSION,
        "anio": anio,
        "exacto_utc": dt_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "lugar": {"lat": lat, "lon": lon, "tz": tz},
        "carta": natal_json(rs),
        "aspectos_con_natal": aspectos_entre(rs, natal),
    }


# --------------------------------------------------------------------------- #
# Contactos: qué toca un evento GLOBAL en una carta
# --------------------------------------------------------------------------- #

def _puntos_de_signo(natal: Natal) -> dict:
    """Puntos natales para el dato de signo: los que reciben aspectos + Mercurio,
    Júpiter y Saturno (§2.2). Sin hora siguen faltando Luna, ASC y MC."""
    puntos = _puntos_natales(natal)
    for nombre in PUNTOS_SOLO_SIGNO:
        puntos[nombre] = natal.posiciones[nombre]["lon"]
    return puntos


def _idx_signo(lon: float) -> int:
    return int(lon // 30) % 12


def contacto(natal: Natal, evento: dict) -> dict:
    """Un evento global medido contra la carta: casa, aspectos al grado,
    puntos natales en el signo y relación con el signo solar.

    `evento`: {clave, tipo, signo, grado?, cuerpo?}. Los ingresos no traen grado:
    un ingreso es un cambio de tono, no un punto, así que no produce aspectos.
    """
    tipo = evento["tipo"]
    idx_evento = SIGNOS.index(evento["signo"])
    grado = evento.get("grado")
    lon_evento = None if (tipo == "ingreso" or grado is None) else idx_evento * 30 + grado

    aspectos: list[dict] = []
    if lon_evento is not None:
        orbe_max = ORBE_CONTACTO.get(tipo, 3.0)
        for punto, punto_lon in _puntos_natales(natal).items():
            for ang, nombre in ASPECTOS.items():
                orbe = abs(separacion(lon_evento, punto_lon) - ang)
                if orbe <= orbe_max:
                    aspectos.append({"punto": punto, "aspecto": nombre,
                                     "orbe": round(orbe, 2)})
        aspectos.sort(key=lambda a: (a["orbe"], ORDEN_PUNTOS.index(a["punto"])))

    # La casa es la del grado del evento. Un ingreso no tiene grado: es el cuerpo
    # recorriendo todo el signo durante semanas, y con Placidus un signo puede
    # repartirse entre dos casas. Se toma la del 15° del signo, donde el cuerpo
    # pasa la mayor parte del tránsito (y donde la rueda dibuja el ingreso): con
    # el 0°, «el Sol entra en Virgo · casa 4» valía para 4 días de 30.
    casa = None
    if natal.hora_conocida:
        lon_casa = idx_evento * 30.0 + 15.0 if lon_evento is None else lon_evento
        casa = casa_de(lon_casa, natal.cuspides)

    de_signo = _puntos_de_signo(natal)
    en_signo = [n for n in ORDEN_PUNTOS
                if n in de_signo and _idx_signo(de_signo[n]) == idx_evento]

    distancia = (idx_evento - _idx_signo(natal.posiciones["sol"]["lon"])) % 12
    return {
        "clave": evento["clave"],
        "lon_evento": None if lon_evento is None else round(lon_evento, 4),
        "casa": casa,
        "aspectos": aspectos,
        "planetas_en_signo": en_signo,
        "relacion_signo_solar": RELACION_SIGNO_SOLAR.get(distancia, "ninguna"),
    }


def contactos(natal: Natal, eventos: list[dict]) -> list[dict]:
    return [contacto(natal, ev) for ev in eventos]


# --------------------------------------------------------------------------- #
# Curaduría de densidad
# --------------------------------------------------------------------------- #

def curar(eventos: list[dict], tz: str = "UTC") -> list[dict]:
    """Máx 6 eventos y máx 2 aspectos por día local. Prioridad: importancia desc,
    desempate por instante exacto más temprano. El orden de salida se preserva."""
    zona = ZoneInfo(tz)
    por_dia: dict[str, list[dict]] = {}
    for ev in eventos:
        dt = datetime.strptime(ev["exacto_utc"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        dia = dt.astimezone(zona).date().isoformat()
        por_dia.setdefault(dia, []).append(ev)

    conservados: set[int] = set()
    for dia, evs in por_dia.items():
        orden = sorted(evs, key=lambda e: (-e["importancia"], e["exacto_utc"]))
        aspectos = 0
        total = 0
        for ev in orden:
            if total >= MAX_EVENTOS_DIA:
                break
            if ev["tipo"] == "aspecto":
                if aspectos >= MAX_ASPECTOS_DIA:
                    continue
                aspectos += 1
            conservados.add(id(ev))
            total += 1
    return [ev for ev in eventos if id(ev) in conservados]


# --------------------------------------------------------------------------- #
# Orquestación
# --------------------------------------------------------------------------- #

def construir_eventos(
    natal: Natal | None,
    desde: date,
    dias: int,
    tz: str = "UTC",
    solo_globales: bool = False,
) -> dict:
    inicio = datetime.combine(desde, time(0, 0), tzinfo=timezone.utc)
    jd_ini = jd_from_dt(inicio)

    globales = eventos_globales(jd_ini, dias)
    personales: list[dict] = []
    if natal is not None and not solo_globales:
        personales = curar(aspectos_personales(natal, jd_ini, dias), tz)

    return {
        "meta": {
            "engine_version": ENGINE_VERSION,
            "ruleset_version": RULESET_VERSION,
            "efemerides": "moshier",
            "generado_en_utc": inicio.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "ventana_dias": dias,
        },
        "natal": natal_json(natal) if natal is not None else None,
        "eventos_globales": globales,
        "eventos_personales": personales,
    }
