"""Club-name normalisation used to reconcile PitchAPI and StrikerAPI.

The two providers use different ids and sometimes different spellings for the
same club ("Bayern München" vs "Bayern Munich", "PSG" vs "Paris Saint-Germain").
Matches are reconciled on normalised team identity plus kickoff date, never on
provider ids.
"""
from __future__ import annotations

import re
import unicodedata
from functools import lru_cache
from typing import Dict, Optional

from backend.config import TEAM_TIMEZONES_FILE
from backend.utils.cache import read_json

# Tokens that carry no identity ("FC Barcelona" == "Barcelona").
_NOISE = {
    "fc", "cf", "afc", "sc", "ac", "as", "ss", "ssc", "sk", "fk", "nk", "bk", "if", "cd",
    "sl", "rc", "rcd", "club", "de", "da", "del", "the", "calcio", "futbol", "football",
    "1", "04", "05", "09", "1899", "1900", "1909", "1913",
}

# Normalised alias -> canonical normalised key. Extend when a provider spells a
# club differently from the other.
ALIASES: Dict[str, str] = {
    "psg": "paris saint germain",
    "paris sg": "paris saint germain",
    "paris": "paris saint germain",
    "bayern munchen": "bayern munich",
    "bayern": "bayern munich",
    "fc bayern": "bayern munich",
    "inter": "internazionale",
    "inter milan": "internazionale",
    "inter milano": "internazionale",
    "internazionale milano": "internazionale",
    "ac milan": "milan",
    "milan": "milan",
    "atletico": "atletico madrid",
    "atl madrid": "atletico madrid",
    "atleti": "atletico madrid",
    "man city": "manchester city",
    "man utd": "manchester united",
    "man united": "manchester united",
    "spurs": "tottenham hotspur",
    "tottenham": "tottenham hotspur",
    "newcastle": "newcastle united",
    "leverkusen": "bayer leverkusen",
    "dortmund": "borussia dortmund",
    "bvb": "borussia dortmund",
    "gladbach": "borussia monchengladbach",
    "leipzig": "rb leipzig",
    "rasenballsport leipzig": "rb leipzig",
    "salzburg": "red bull salzburg",
    "rb salzburg": "red bull salzburg",
    "sporting": "sporting cp",
    "sporting lisbon": "sporting cp",
    "sporting clube portugal": "sporting cp",
    "benfica": "benfica",
    "sl benfica": "benfica",
    "porto": "porto",
    "psv": "psv eindhoven",
    "psv eindhoven": "psv eindhoven",
    "ajax amsterdam": "ajax",
    "feyenoord rotterdam": "feyenoord",
    "club brugge kv": "club brugge",
    "brugge": "club brugge",
    "union saint gilloise": "union st gilloise",
    "royale union saint gilloise": "union st gilloise",
    "union sg": "union st gilloise",
    "olympiacos piraeus": "olympiacos",
    "olympiakos": "olympiacos",
    "galatasaray sk": "galatasaray",
    "fenerbahce sk": "fenerbahce",
    "slavia prague": "slavia praha",
    "sparta prague": "sparta praha",
    "dinamo zagreb": "dinamo zagreb",
    "gnk dinamo zagreb": "dinamo zagreb",
    "red star belgrade": "crvena zvezda",
    "fk crvena zvezda": "crvena zvezda",
    "young boys": "young boys",
    "bsc young boys": "young boys",
    "copenhagen": "kobenhavn",
    "fc copenhagen": "kobenhavn",
    "bodo glimt": "bodo glimt",
    "fk bodo glimt": "bodo glimt",
    "qarabag fk": "qarabag",
    "kairat almaty": "kairat",
    "pafos fc": "pafos",
    "athletic bilbao": "athletic club",
    "athletic": "athletic club",
    "villarreal cf": "villarreal",
    "real sociedad": "real sociedad",
    "sevilla fc": "sevilla",
    "napoli": "napoli",
    "ssc napoli": "napoli",
    "as roma": "roma",
    "juve": "juventus",
    "eintracht": "eintracht frankfurt",
    "frankfurt": "eintracht frankfurt",
    "stuttgart": "vfb stuttgart",
    "celtic glasgow": "celtic",
    "rangers fc": "rangers",
    "monaco": "monaco",
    "as monaco": "monaco",
    "marseille": "marseille",
    "olympique marseille": "marseille",
    "olympique de marseille": "marseille",
    "lyon": "lyon",
    "olympique lyonnais": "lyon",
    "lille": "lille",
    "losc lille": "lille",
    "brest": "brest",
    "stade brestois": "brest",
    "stade brestois 29": "brest",
    "sturm graz": "sturm graz",
    "sk sturm graz": "sturm graz",
}


def _strip_accents(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


def normalize_team_name(name: Optional[str]) -> str:
    """Return a canonical comparison key for a club name ("" when unknown)."""
    if not name:
        return ""
    text = _strip_accents(str(name)).lower()
    text = text.replace("&", " and ").replace("ø", "o").replace("æ", "ae").replace("ß", "ss")
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if text in ALIASES:
        return ALIASES[text]
    tokens = [t for t in text.split(" ") if t and t not in _NOISE]
    core = " ".join(tokens) or text
    return ALIASES.get(core, core)


def same_team(a: Optional[str], b: Optional[str]) -> bool:
    na, nb = normalize_team_name(a), normalize_team_name(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    # Tolerate one name being a strict word-subset of the other
    # ("Real Madrid" vs "Real Madrid CF" after normalisation, "Benfica" vs "SL Benfica").
    sa, sb = set(na.split()), set(nb.split())
    small, big = (sa, sb) if len(sa) <= len(sb) else (sb, sa)
    return len(small) >= 1 and small.issubset(big) and len("".join(small)) >= 5


@lru_cache(maxsize=1)
def _timezone_map() -> Dict[str, str]:
    raw = read_json(TEAM_TIMEZONES_FILE, default={}) or {}
    clubs = raw.get("clubs", {}) if isinstance(raw, dict) else {}
    return {normalize_team_name(k): v for k, v in clubs.items() if isinstance(v, str)}


def home_timezone_for(team_name: Optional[str]) -> Optional[str]:
    """IANA timezone of the home club's city, when known.

    UCL home fixtures are played in the home club's country, so the home club's
    timezone is the venue's timezone. Returns ``None`` for clubs not in
    ``data/team_timezones.json`` — the UI then shows PKT only.
    """
    key = normalize_team_name(team_name)
    if not key:
        return None
    mapping = _timezone_map()
    if key in mapping:
        return mapping[key]
    for known, tz in mapping.items():
        if same_team(known, key):
            return tz
    return None
