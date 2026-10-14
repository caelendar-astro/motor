# Caelendar · motor de cálculo

Servicio HTTP sin estado que calcula la parte astronómica y astrológica de
[Caelendar](https://caelendar.com): cartas natales, eventos del cielo, tránsitos sobre una
carta, revoluciones solares y qué toca cada evento global en una carta concreta. No conoce
usuarios, cuentas ni pagos: recibe datos natales y fechas y devuelve JSON.

Este repositorio es el código exacto que corre en producción. Cada versión desplegada tiene
su tag (`v1.10.1`, …).

## Licencia

**GNU Affero General Public License v3.0** (ver `LICENSE`).
Copyright © 2026 MARGOT CLOUD, S.L.

El motor usa [Swiss Ephemeris](https://www.astro.com/swisseph/) de Astrodienst AG, a través
de [pyswisseph](https://github.com/astrorigin/pyswisseph), ambos bajo AGPL-3.0.

## Correr

```
docker build -t caelendar-motor .
docker run --rm -p 8100:8100 caelendar-motor
curl -s localhost:8100/health
docker run --rm caelendar-motor pytest -q
```

## Contrato

- `POST /natal`: `{birth_date, birth_time|null, lat, lon, birth_tz, time_known}` →
  `{engine_version, ruleset_version, natal: {planetas, ascendente|null, medio_cielo|null,
  casas|null, aspectos}}`. Hora desconocida (`time_known=false`) → mediodía local, sin
  ASC/MC ni casas. `aspectos`: `[{a, b, aspecto, orbe}]` entre los puntos de la propia carta,
  por orbe ascendente.
- `POST /eventos`: `{natal|null, desde, dias, tz, solo_globales}` →
  `{meta, natal|null, eventos_globales, eventos_personales}`. `tz` agrupa la curaduría por
  día local.
- `POST /contactos`: `{natal, eventos: [{clave, tipo, signo, grado?, cuerpo?}]}` →
  `{meta, contactos: [{clave, lon_evento, casa, aspectos, planetas_en_signo,
  relacion_signo_solar}]}`. Mide un evento global contra una carta. `clave` vuelve intacta.
- `POST /revolucion-solar`: `{natal, anio, lat, lon, tz}` → `{engine_version,
  ruleset_version, anio, exacto_utc, lugar, carta, aspectos_con_natal}`. `exacto_utc` es el
  instante en que el Sol vuelve a su longitud natal, buscado desde el cumpleaños civil −2 días
  durante 5 días (un 29 de febrero busca desde el 28); una sola raíz o 422. El lugar no mueve
  el instante, solo casas y ángulos. `aspectos_con_natal`: `[{rs, natal, aspecto, orbe}]`,
  uno por par, por orbe ascendente; Sol RS – Sol natal va primero.
- `GET /health`.

## Reglas

- Cuerpos: Sol, Luna, Mercurio, Venus, Marte, Júpiter, Saturno. Transitan todos menos la Luna.
- Puntos natales que reciben tránsitos: Sol, Venus y Marte siempre; Luna, ASC y MC solo con
  hora conocida.
- Aspectos mayores (0/60/90/120/180). Orbe por cuerpo en tránsito: Sol 2°, Mercurio, Venus y
  Marte 1°, Júpiter y Saturno 1,5°. Un retorno es la conjunción del cuerpo consigo mismo.
- Eventos globales: lunaciones, estaciones de Mercurio, ingresos de Sol, Mercurio, Venus y
  Marte, eclipses. Un eclipse reemplaza a la lunación del mismo día.
- Importancia 1–5: eclipses 5; lunaciones, aspectos de Júpiter y Saturno, retornos de Venus y
  Marte y conjunciones u oposiciones a Sol, Luna o ASC natales 4; el resto de aspectos y las
  estaciones de Mercurio 3; ingreso del Sol 2; otros ingresos 1. El retorno del Sol es 5.
- Curaduría: como máximo 6 eventos y 2 aspectos personales por día local, por importancia.
- Aspectos natales: orbes de 7° (conjunción, oposición), 6° (cuadratura, trígono) y 4°
  (sextil); 4° si interviene ASC o MC; nunca el par ASC–MC; un aspecto por par.
- Casas Placidus; Porfirio desde 66° de latitud, donde Placidus no está definido. Grados
  cotejados al minuto contra cartas de referencia.
- Contactos: casa del grado del evento (de un ingreso, la del 15° del signo); aspectos al
  grado con orbe 3° (lunaciones, eclipses) o 2° (estaciones de Mercurio); los ingresos no
  aspectan; puntos natales en el signo del evento; relación con el signo solar.

## Decisiones técnicas

- Efemérides Moshier (`FLG_MOSEPH`): integradas en Swiss Ephemeris, sin archivos externos.
  Precisión de segundos de arco, muy por debajo de los orbes.
- Instantes exactos por muestreo (grilla de 6–12 h) y bisección (~60 iteraciones).
- Ingresos robustos al paso de 360° a 0°.
- `engine_version` y `ruleset_version` en cada salida, para recalcular de forma controlada.
