#!/usr/bin/env python3
"""Enrich normalized collection JSON with Scryfall metadata and images."""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

API_BASE = "https://api.scryfall.com"
USER_AGENT = "ColeccionMtgMVP/0.1 local-script"

LANG_MAP = {
    "en": "en", "eng": "en", "english": "en", "ingles": "en", "inglés": "en",
    "es": "es", "esp": "es", "spanish": "es", "espanol": "es", "español": "es",
    "fr": "fr", "fra": "fr", "french": "fr", "frances": "fr", "francés": "fr",
    "de": "de", "ger": "de", "german": "de", "aleman": "de", "alemán": "de",
    "it": "it", "ita": "it", "italian": "it", "italiano": "it",
    "pt": "pt", "por": "pt", "portuguese": "pt", "portugues": "pt", "portugués": "pt",
    "ja": "ja", "jp": "ja", "japanese": "ja", "japones": "ja", "japonés": "ja",
    "ko": "ko", "korean": "ko", "coreano": "ko",
    "ru": "ru", "russian": "ru", "ruso": "ru",
    "zhs": "zhs", "zh-s": "zhs", "chinese simplified": "zhs",
    "zht": "zht", "zh-t": "zht", "chinese traditional": "zht",
}


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def normalize_text(value: Any) -> str:
    text = "" if value is None else str(value)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def language_code(value: Any) -> Optional[str]:
    if value is None:
        return None
    key = normalize_text(value).replace(" ", "")
    return LANG_MAP.get(key, key if len(key) in {2, 3} else None)


def quote_exact_name(name: str) -> str:
    escaped = name.replace('"', '\\"')
    return f'!"{escaped}"'


def cache_key(card: Dict[str, Any]) -> str:
    parts = [
        card.get("scryfallId"),
        card.get("lookupName") or card.get("cardName"),
        card.get("edition"),
        card.get("setCode"),
        card.get("collectorNumber"),
        card.get("language"),
        card.get("foiling"),
    ]
    return "|".join(normalize_text(p) for p in parts if p is not None)


def request_json(path: str, params: Optional[Dict[str, str]] = None, offline: bool = False) -> Optional[Dict[str, Any]]:
    if offline:
        return None
    url = API_BASE + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code in {404, 422}:
            return None
        print(f"Scryfall HTTP error {exc.code}: {url}", file=sys.stderr)
        return None
    except Exception as exc:
        print(f"Scryfall request failed: {exc} for {url}", file=sys.stderr)
        return None


def score_candidate(card: Dict[str, Any], row: Dict[str, Any], edition_aliases: Dict[str, str]) -> int:
    score = 0
    name = normalize_text(row.get("cardName"))
    cand_name = normalize_text(card.get("name"))
    if name and cand_name == name:
        score += 50
    elif name and name in cand_name:
        score += 25

    row_set_code = normalize_text(row.get("setCode"))
    edition = row.get("edition")
    edition_norm = normalize_text(edition)
    alias_code = edition_aliases.get(edition_norm) or edition_aliases.get(str(edition or ""))
    cand_set = normalize_text(card.get("set"))
    cand_set_name = normalize_text(card.get("set_name"))
    if row_set_code and cand_set == row_set_code:
        score += 40
    if alias_code and cand_set == normalize_text(alias_code):
        score += 40
    if edition_norm and (edition_norm == cand_set_name or edition_norm in cand_set_name or cand_set_name in edition_norm):
        score += 30

    row_number = normalize_text(row.get("collectorNumber"))
    cand_number = normalize_text(card.get("collector_number"))
    if row_number and cand_number and row_number == cand_number:
        score += 40

    row_lang = language_code(row.get("language"))
    if row_lang and row_lang == card.get("lang"):
        score += 10

    foil = normalize_text(row.get("foiling"))
    if foil:
        finishes = [normalize_text(x) for x in card.get("finishes", [])]
        if "foil" in foil and "foil" in finishes:
            score += 10
        if "nonfoil" in foil and "nonfoil" in finishes:
            score += 10
    return score


def pick_images(card: Dict[str, Any]) -> Dict[str, Any]:
    images = card.get("image_uris") or {}
    faces = card.get("card_faces") or []
    front_images = images
    back_images = None
    if not front_images and faces:
        front_images = faces[0].get("image_uris") or {}
        if len(faces) > 1:
            back_images = faces[1].get("image_uris") or None
    return {
        "small": front_images.get("small"),
        "normal": front_images.get("normal"),
        "large": front_images.get("large"),
        "png": front_images.get("png"),
        "artCrop": front_images.get("art_crop"),
        "backNormal": (back_images or {}).get("normal") if back_images else None,
        "status": card.get("image_status"),
    }


def direct_by_id(scryfall_id: str, offline: bool) -> Optional[Dict[str, Any]]:
    return request_json(f"/cards/{urllib.parse.quote(str(scryfall_id))}", offline=offline)


def search_scryfall(query: str, offline: bool) -> List[Dict[str, Any]]:
    payload = request_json("/cards/search", {
        "q": query,
        "unique": "prints",
        "order": "released",
        "dir": "desc",
    }, offline=offline)
    if not payload:
        return []
    return payload.get("data", []) or []


def search_candidates(row: Dict[str, Any], edition_aliases: Dict[str, str], offline: bool) -> Tuple[Optional[Dict[str, Any]], str, str, int]:
    if offline:
        return None, "offline", "", 0
    name = str(row.get("lookupName") or row.get("cardName") or "").strip()
    if not name:
        return None, "missing-name", "", 0

    row_lang = language_code(row.get("language"))
    edition_norm = normalize_text(row.get("edition"))
    set_code = row.get("setCode") or edition_aliases.get(edition_norm) or edition_aliases.get(str(row.get("edition") or ""))
    collector_number = row.get("collectorNumber")

    queries: List[Tuple[str, str]] = []
    if set_code and collector_number:
        queries.append(("exact-name+set+number", f"{quote_exact_name(name)} e:{set_code} cn:{collector_number}"))
    if set_code:
        queries.append(("exact-name+set", f"{quote_exact_name(name)} e:{set_code}"))
    if row_lang:
        queries.append(("exact-name+lang", f"{quote_exact_name(name)} lang:{row_lang}"))
    queries.append(("exact-name", quote_exact_name(name)))
    queries.append(("name-search", name))

    seen_queries = set()
    best: Optional[Dict[str, Any]] = None
    best_score = -1
    best_label = "not-found"
    best_query = ""
    for label, query in queries:
        if query in seen_queries:
            continue
        seen_queries.add(query)
        candidates = search_scryfall(query, offline=offline)
        if not candidates:
            time.sleep(0.55)
            continue
        for candidate in candidates:
            score = score_candidate(candidate, row, edition_aliases)
            if score > best_score:
                best = candidate
                best_score = score
                best_label = label
                best_query = query
        if best_score >= 100:
            break
        time.sleep(0.55)
    return best, best_label, best_query, max(best_score, 0)


def enrich_card(row: Dict[str, Any], edition_aliases: Dict[str, str], manual_matches: Dict[str, Any], cache: Dict[str, Any], offline: bool) -> Dict[str, Any]:
    key = cache_key(row)
    tcg = normalize_text(row.get("tcg"))
    if tcg and "magic" not in tcg:
        enrichment = {
            "scryfall": {"matched": False, "matchedBy": "non-mtg", "query": "", "score": 0, "needsReview": True},
            "image": {"small": None, "normal": None, "large": None, "png": None, "status": None},
            "needsReview": True,
        }
        return {**row, **enrichment}
    if key in cache:
        cached = cache[key]
        if isinstance(cached, dict):
            return {**row, **cached}

    manual_key = row.get("internalId") or key
    manual = manual_matches.get(manual_key) or manual_matches.get(key)
    scryfall_id = row.get("scryfallId") or (manual.get("scryfallId") if isinstance(manual, dict) else manual)

    if offline and not scryfall_id:
        enrichment = {
            "scryfall": {"matched": False, "matchedBy": "offline", "query": "", "score": 0, "needsReview": True},
            "image": {"small": None, "normal": None, "large": None, "png": None, "status": None},
            "needsReview": True,
        }
        return {**row, **enrichment}

    card = None
    method = ""
    query = ""
    score = 0
    if scryfall_id:
        card = direct_by_id(str(scryfall_id), offline=offline)
        method = "scryfall-id"
        score = 100 if card else 0
        time.sleep(0.55)
    if not card:
        card, method, query, score = search_candidates(row, edition_aliases, offline=offline)

    if not card:
        enrichment = {
            "scryfall": {
                "matched": False,
                "matchedBy": method or "not-found",
                "query": query,
                "score": score,
                "needsReview": True,
            },
            "image": {"small": None, "normal": None, "large": None, "png": None, "status": None},
            "needsReview": True,
        }
        cache[key] = enrichment
        return {**row, **enrichment}

    images = pick_images(card)
    price_info = card.get("prices") or {}
    purchase_uris = card.get("purchase_uris") or {}
    enrichment = {
        "cardName": row.get("cardName") or card.get("name"),
        "edition": row.get("edition") or card.get("set_name"),
        "setCode": row.get("setCode") or card.get("set"),
        "collectorNumber": row.get("collectorNumber") or card.get("collector_number"),
        "scryfall": {
            "matched": True,
            "matchedBy": method,
            "query": query,
            "score": score,
            "needsReview": score < 70,
            "id": card.get("id"),
            "oracleId": card.get("oracle_id"),
            "name": card.get("name"),
            "printedName": card.get("printed_name"),
            "lang": card.get("lang"),
            "set": card.get("set"),
            "setName": card.get("set_name"),
            "collectorNumber": card.get("collector_number"),
            "rarity": card.get("rarity"),
            "uri": card.get("scryfall_uri"),
            "releasedAt": card.get("released_at"),
        },
        "image": images,
        "prices": {
            "scryfallEur": price_info.get("eur"),
            "scryfallEurFoil": price_info.get("eur_foil"),
            "scryfallUsd": price_info.get("usd"),
            "scryfallUsdFoil": price_info.get("usd_foil"),
        },
        "cardmarketUrl": row.get("cardmarketUrl") or purchase_uris.get("cardmarket"),
        "needsReview": score < 70 or not images.get("normal"),
    }
    cache[key] = enrichment
    return {**row, **enrichment}


def main() -> int:
    parser = argparse.ArgumentParser(description="Enrich collection JSON with Scryfall images and metadata")
    parser.add_argument("--input", default="data/collection.raw.json")
    parser.add_argument("--out", default="data/collection.enriched.json")
    parser.add_argument("--cache", default="data/scryfall-cache.json")
    parser.add_argument("--edition-aliases", default="config/edition_aliases.json")
    parser.add_argument("--manual-matches", default="config/manual_scryfall_matches.json")
    parser.add_argument("--base-dir", default=".")
    parser.add_argument("--offline", action="store_true", help="Do not call Scryfall; only use cache/manual data")
    args = parser.parse_args()

    base_dir = Path(args.base_dir).resolve()
    input_path = base_dir / args.input
    out_path = base_dir / args.out
    cache_path = base_dir / args.cache
    aliases_path = base_dir / args.edition_aliases
    manual_path = base_dir / args.manual_matches

    payload = load_json(input_path, None)
    if payload is None:
        raise FileNotFoundError(f"Input JSON not found: {input_path}")
    edition_aliases = {normalize_text(k): v for k, v in load_json(aliases_path, {}).items()}
    manual_matches = load_json(manual_path, {})
    cache = load_json(cache_path, {})

    enriched_cards = []
    for idx, row in enumerate(payload.get("cards", []), start=1):
        print(f"[{idx}/{len(payload.get('cards', []))}] {row.get('cardName')} - {row.get('edition')}")
        enriched_cards.append(enrich_card(row, edition_aliases, manual_matches, cache, offline=args.offline))
        if idx % 10 == 0:
            save_json(cache_path, cache)

    result = {
        **payload,
        "generatedAt": datetime.now().astimezone().isoformat(timespec="seconds"),
        "enrichment": {
            "source": "scryfall",
            "offline": args.offline,
            "cacheFile": str(cache_path),
            "unmatched": sum(1 for c in enriched_cards if not c.get("scryfall", {}).get("matched")),
            "needsReview": sum(1 for c in enriched_cards if c.get("needsReview")),
        },
        "cards": enriched_cards,
    }
    save_json(out_path, result)
    save_json(cache_path, cache)
    print(f"Wrote {out_path} with {len(enriched_cards)} enriched rows")
    print(f"Needs review: {result['enrichment']['needsReview']} | Unmatched: {result['enrichment']['unmatched']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
