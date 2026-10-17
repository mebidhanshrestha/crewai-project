"""Ganita: deterministic chart maths. No LLM touches these numbers.

Sidereal (Lahiri) positions from Swiss Ephemeris, whole-sign houses,
dignities, Moon nakshatra and the running Vimshottari dasha.
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import swisseph as swe

SIGNS = [
    "Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo",
    "Libra", "Scorpio", "Sagittarius", "Capricorn", "Aquarius", "Pisces",
]

SIGN_LORDS = {
    "Aries": "Mars", "Taurus": "Venus", "Gemini": "Mercury", "Cancer": "Moon",
    "Leo": "Sun", "Virgo": "Mercury", "Libra": "Venus", "Scorpio": "Mars",
    "Sagittarius": "Jupiter", "Capricorn": "Saturn", "Aquarius": "Saturn",
    "Pisces": "Jupiter",
}

EXALTATION = {
    "Sun": "Aries", "Moon": "Taurus", "Mars": "Capricorn", "Mercury": "Virgo",
    "Jupiter": "Cancer", "Venus": "Pisces", "Saturn": "Libra",
}

OWN_SIGNS = {
    "Sun": ["Leo"], "Moon": ["Cancer"], "Mars": ["Aries", "Scorpio"],
    "Mercury": ["Gemini", "Virgo"], "Jupiter": ["Sagittarius", "Pisces"],
    "Venus": ["Taurus", "Libra"], "Saturn": ["Capricorn", "Aquarius"],
}

PLANETS = {
    "Sun": swe.SUN, "Moon": swe.MOON, "Mars": swe.MARS, "Mercury": swe.MERCURY,
    "Jupiter": swe.JUPITER, "Venus": swe.VENUS, "Saturn": swe.SATURN,
    "Rahu": swe.MEAN_NODE,
}

NAKSHATRAS = [
    "Ashwini", "Bharani", "Krittika", "Rohini", "Mrigashira", "Ardra",
    "Punarvasu", "Pushya", "Ashlesha", "Magha", "Purva Phalguni",
    "Uttara Phalguni", "Hasta", "Chitra", "Swati", "Vishakha", "Anuradha",
    "Jyeshtha", "Mula", "Purva Ashadha", "Uttara Ashadha", "Shravana",
    "Dhanishta", "Shatabhisha", "Purva Bhadrapada", "Uttara Bhadrapada",
    "Revati",
]

# Vimshottari order and years (total 120). Ashwini starts with Ketu.
DASHA_ORDER = ["Ketu", "Venus", "Sun", "Moon", "Mars", "Rahu", "Jupiter", "Saturn", "Mercury"]
DASHA_YEARS = {
    "Ketu": 7, "Venus": 20, "Sun": 6, "Moon": 10, "Mars": 7,
    "Rahu": 18, "Jupiter": 16, "Saturn": 19, "Mercury": 17,
}

NAKSHATRA_SPAN = 360 / 27
YEAR_DAYS = 365.25


def sign_of(longitude: float) -> str:
    return SIGNS[int(longitude // 30) % 12]


def dignity(planet: str, sign: str) -> str:
    if planet not in EXALTATION:
        return "neutral"  # nodes have no classical dignity here
    if EXALTATION[planet] == sign:
        return "exalted"
    if SIGNS[(SIGNS.index(EXALTATION[planet]) + 6) % 12] == sign:
        return "debilitated"
    if sign in OWN_SIGNS[planet]:
        return "own"
    return "neutral"


def vimshottari(moon_longitude: float, birth_utc: datetime, on: datetime) -> dict:
    """Return the mahadasha and antardasha running on `on`."""
    index = int(moon_longitude // NAKSHATRA_SPAN)
    traversed = (moon_longitude % NAKSHATRA_SPAN) / NAKSHATRA_SPAN
    start_lord = DASHA_ORDER[index % 9]

    # The first mahadasha began before birth by the part already traversed.
    md_start = birth_utc - timedelta(days=traversed * DASHA_YEARS[start_lord] * YEAR_DAYS)
    i = DASHA_ORDER.index(start_lord)
    while True:
        md_lord = DASHA_ORDER[i % 9]
        md_years = DASHA_YEARS[md_lord]
        md_end = md_start + timedelta(days=md_years * YEAR_DAYS)
        if md_end > on:
            break
        md_start, i = md_end, i + 1

    # Antardashas run in the same order, starting from the mahadasha lord.
    ad_start = md_start
    j = DASHA_ORDER.index(md_lord)
    while True:
        ad_lord = DASHA_ORDER[j % 9]
        ad_end = ad_start + timedelta(days=md_years * DASHA_YEARS[ad_lord] / 120 * YEAR_DAYS)
        if ad_end > on:
            break
        ad_start, j = ad_end, j + 1

    return {
        "mahadasha": md_lord,
        "mahadasha_until": md_end.date().isoformat(),
        "antardasha": ad_lord,
        "antardasha_until": ad_end.date().isoformat(),
    }


def compute_chart(date: str, time: str, latitude: float, longitude: float,
                  timezone: str, on: datetime | None = None) -> dict:
    """Build a sidereal birth chart. `date` is YYYY-MM-DD, `time` is HH:MM (local)."""
    local = datetime.fromisoformat(f"{date}T{time}").replace(tzinfo=ZoneInfo(timezone))
    utc = local.astimezone(ZoneInfo("UTC"))
    on = on or datetime.now(ZoneInfo("UTC"))

    swe.set_sid_mode(swe.SIDM_LAHIRI)
    flags = swe.FLG_SIDEREAL | swe.FLG_MOSEPH  # Moshier: no ephemeris files needed
    jd = swe.julday(utc.year, utc.month, utc.day,
                    utc.hour + utc.minute / 60 + utc.second / 3600)

    _, ascmc = swe.houses_ex(jd, latitude, longitude, b"W", flags)
    lagna = sign_of(ascmc[0])
    lagna_index = SIGNS.index(lagna)

    positions = {name: swe.calc_ut(jd, pid, flags)[0][0] for name, pid in PLANETS.items()}
    positions["Ketu"] = (positions["Rahu"] + 180) % 360

    planets = {}
    for name, lon in positions.items():
        sign = sign_of(lon)
        planets[name] = {
            "sign": sign,
            "degree": round(lon % 30, 2),
            "house": (SIGNS.index(sign) - lagna_index) % 12 + 1,
            "dignity": dignity(name, sign),
        }

    house_lords = {h: SIGN_LORDS[SIGNS[(lagna_index + h - 1) % 12]] for h in range(1, 13)}
    moon = positions["Moon"]

    return {
        "lagna": lagna,
        "moon_sign": planets["Moon"]["sign"],
        "nakshatra": NAKSHATRAS[int(moon // NAKSHATRA_SPAN)],
        "planets": planets,
        "house_lords": house_lords,
        "dasha": vimshottari(moon, utc, on),
    }
