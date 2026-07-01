#!/usr/bin/env python3
"""Fetch tournament data for the static site.

The browser reads data/cache.json first, so visitors do not need direct access
to Wikipedia/ESPN/Elo sources. This script is intentionally dependency-free so
it can run inside GitHub Actions without installing packages.
"""

from __future__ import annotations

import datetime as dt
import json
import pathlib
import re
import time
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "cache.json"

WIKI_API = "https://en.wikipedia.org/w/api.php"
ESPN_API = "https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/scoreboard"
ELO_URL = "https://r.jina.ai/http://www.eloratings.net/2026_World_Cup.tsv"
POLYMARKET_URL = "https://polymarket.com/sports/world-cup/games"


def fetch_json(url: str, timeout: int = 25) -> dict:
    request = urllib.request.Request(url, headers={"User-Agent": "worldcup-knockout-cache/1.0"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_text(url: str, timeout: int = 25) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 worldcup-knockout-cache/1.0"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="replace")


def with_retries(fn, *, attempts: int = 3, delay: float = 1.5):
    last_error: Exception | None = None
    for i in range(attempts):
        try:
            return fn()
        except Exception as error:  # noqa: BLE001 - keep script resilient in Actions
            last_error = error
            if i < attempts - 1:
                time.sleep(delay * (i + 1))
    raise last_error  # type: ignore[misc]


def wiki_parse(page: str) -> dict:
    query = urllib.parse.urlencode(
        {
            "action": "parse",
            "prop": "text|revid",
            "format": "json",
            "maxage": "0",
            "smaxage": "0",
            "page": page,
        }
    )
    return with_retries(lambda: fetch_json(f"{WIKI_API}?{query}"))


def date_keys() -> list[str]:
    # Use a wider window than the browser used. This protects against timezone
    # boundaries while still keeping the JSON small.
    today = dt.datetime.now(dt.UTC).date()
    return [(today + dt.timedelta(days=offset)).strftime("%Y%m%d") for offset in range(-2, 4)]


def espn_scoreboard(date_key: str) -> dict:
    query = urllib.parse.urlencode({"dates": date_key})
    return with_retries(lambda: fetch_json(f"{ESPN_API}?{query}"))


def polymarket_games() -> dict:
    """Extract World Cup 1X2 prices from the public Polymarket sports page.

    The page renders each trading button twice for responsive layouts, followed
    later by single winner-only buttons. We keep the first full sequence of
    HOME / DRAW / AWAY prices.
    """
    try:
        html = with_retries(lambda: fetch_text(POLYMARKET_URL, timeout=20), attempts=2)
        pairs = re.findall(
            r'<span class="opacity-70[^>]*>\s*([A-Z0-9]{2,5}|DRAW)\s*</span>'
            r'<span[^>]*class="ml-1 text-sm">\s*([0-9.]+)¢\s*</span>',
            html,
        )
        compact: list[tuple[str, str]] = []
        for pair in pairs:
            if not compact or compact[-1] != pair:
                compact.append(pair)
        matches = []
        for i in range(0, len(compact) - 2, 3):
            home, draw, away = compact[i : i + 3]
            if draw[0] != "DRAW" or home[0] == "DRAW" or away[0] == "DRAW":
                break
            matches.append(
                {
                    "homeCode": home[0],
                    "awayCode": away[0],
                    "home": float(home[1]),
                    "draw": float(draw[1]),
                    "away": float(away[1]),
                }
            )
        return {"source": POLYMARKET_URL, "matches": matches}
    except Exception as error:  # noqa: BLE001 - optional signal, never block cache
        return {"source": POLYMARKET_URL, "matches": [], "error": str(error)}


def main() -> None:
    generated_at = dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    pages = {
        "worldCup": wiki_parse("2026_FIFA_World_Cup"),
        "knockout": wiki_parse("2026_FIFA_World_Cup_knockout_stage"),
    }
    # Keep previously fetched match days. A rolling date window alone makes
    # completed knockout results disappear from the static site a few days
    # later, causing finished cards to fall back to projected matchups.
    previous_espn: dict[str, dict] = {}
    if OUT.exists():
        try:
            previous = json.loads(OUT.read_text(encoding="utf-8"))
            previous_espn = previous.get("espn", {}) if isinstance(previous.get("espn", {}), dict) else {}
        except (OSError, ValueError, TypeError):
            previous_espn = {}
    espn = {**previous_espn, **{key: espn_scoreboard(key) for key in date_keys()}}
    elo_text = with_retries(lambda: fetch_text(ELO_URL))
    polymarket = polymarket_games()

    payload = {
        "schemaVersion": 1,
        "generatedAt": generated_at,
        "sources": {
            "wikipedia": "https://en.wikipedia.org/wiki/2026_FIFA_World_Cup",
            "knockout": "https://en.wikipedia.org/wiki/2026_FIFA_World_Cup_knockout_stage",
            "espn": ESPN_API,
            "elo": ELO_URL,
            "polymarket": POLYMARKET_URL,
        },
        "wiki": pages,
        "espn": espn,
        "eloText": elo_text,
        "polymarket": polymarket,
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"Wrote {OUT.relative_to(ROOT)} at {generated_at}")


if __name__ == "__main__":
    main()
