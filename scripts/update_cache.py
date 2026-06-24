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
import time
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "cache.json"

WIKI_API = "https://en.wikipedia.org/w/api.php"
ESPN_API = "https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/scoreboard"
ELO_URL = "https://r.jina.ai/http://www.eloratings.net/2026_World_Cup.tsv"


def fetch_json(url: str, timeout: int = 25) -> dict:
    request = urllib.request.Request(url, headers={"User-Agent": "worldcup-knockout-cache/1.0"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_text(url: str, timeout: int = 25) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "worldcup-knockout-cache/1.0"})
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


def main() -> None:
    generated_at = dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    pages = {
        "worldCup": wiki_parse("2026_FIFA_World_Cup"),
        "knockout": wiki_parse("2026_FIFA_World_Cup_knockout_stage"),
    }
    espn = {key: espn_scoreboard(key) for key in date_keys()}
    elo_text = with_retries(lambda: fetch_text(ELO_URL))

    payload = {
        "schemaVersion": 1,
        "generatedAt": generated_at,
        "sources": {
            "wikipedia": "https://en.wikipedia.org/wiki/2026_FIFA_World_Cup",
            "knockout": "https://en.wikipedia.org/wiki/2026_FIFA_World_Cup_knockout_stage",
            "espn": ESPN_API,
            "elo": ELO_URL,
        },
        "wiki": pages,
        "espn": espn,
        "eloText": elo_text,
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"Wrote {OUT.relative_to(ROOT)} at {generated_at}")


if __name__ == "__main__":
    main()
