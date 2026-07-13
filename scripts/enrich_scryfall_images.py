#!/usr/bin/env python3
"""Optional image enrichment for portfolio-data.json.

This script queries Scryfall only for Magic: The Gathering rows already present
in the filtered JSON and writes the image URIs back to JSON and JS. It is
intended to be run locally before committing to Git so the published page does
not need to resolve images on every visit.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

USER_AGENT = "mi-coleccion-tcgs/1.0"
SCRYFALL_NAMED = "https://api.scryfall.com/cards/named"


def request_json(url: str) -> dict | None:
    req = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with urlopen(req, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        print(f"  Aviso: no se pudo consultar {url}: {exc}")
        return None


def get_image_uris(card: dict) -> dict:
    if card.get("image_uris"):
        return card["image_uris"]
    faces = card.get("card_faces") or []
    for face in faces:
        if face.get("image_uris"):
            return face["image_uris"]
    return {}


def lookup_card(name: str) -> dict | None:
    if not name:
        return None
    exact_url = SCRYFALL_NAMED + "?" + urlencode({"exact": name})
    result = request_json(exact_url)
    if result and result.get("object") == "card":
        return result
    fuzzy_url = SCRYFALL_NAMED + "?" + urlencode({"fuzzy": name})
    return request_json(fuzzy_url)


def enrich(data_path: Path, delay_seconds: float, limit: int | None) -> dict:
    payload = json.loads(data_path.read_text(encoding="utf-8"))
    cards = payload.get("cards", [])
    resolved = 0
    skipped = 0
    failed = 0

    for card in cards:
        if limit is not None and resolved >= limit:
            break
        tcg = str(card.get("tcg") or "").lower()
        if "magic" not in tcg:
            skipped += 1
            continue
        if card.get("images", {}).get("normal"):
            skipped += 1
            continue
        name = card.get("scryfallName") or card.get("cardName") or card.get("name")
        print(f"Consultando Scryfall: {name}")
        result = lookup_card(name)
        time.sleep(delay_seconds)
        if not result or result.get("object") != "card":
            failed += 1
            card.setdefault("images", {})["status"] = "not_found"
            continue
        image_uris = get_image_uris(result)
        if not image_uris:
            failed += 1
            card.setdefault("images", {})["status"] = "no_image"
            continue
        card["images"] = {
            "small": image_uris.get("small", ""),
            "normal": image_uris.get("normal", ""),
            "large": image_uris.get("large", ""),
            "artCrop": image_uris.get("art_crop", ""),
            "status": "resolved",
        }
        card["scryfall"] = {
            "id": result.get("id", ""),
            "uri": result.get("scryfall_uri", ""),
            "apiUri": result.get("uri", ""),
            "set": result.get("set", ""),
            "setName": result.get("set_name", ""),
            "collectorNumber": result.get("collector_number", ""),
            "resolved": True,
        }
        resolved += 1

    payload.setdefault("metadata", {}).setdefault("imageResolution", {})
    image_meta = payload["metadata"]["imageResolution"]
    image_meta["resolvedRows"] = sum(1 for c in cards if c.get("images", {}).get("status") == "resolved")
    image_meta["pendingRows"] = sum(1 for c in cards if c.get("images", {}).get("status") == "pending")
    image_meta["notFoundRows"] = sum(1 for c in cards if c.get("images", {}).get("status") in {"not_found", "no_image"})

    text = json.dumps(payload, ensure_ascii=False, indent=2)
    data_path.write_text(text + "\n", encoding="utf-8")
    js_path = data_path.with_suffix(".js")
    js_path.write_text("window.portfolioData = " + text + ";\n", encoding="utf-8")
    return {"resolved": resolved, "skipped": skipped, "failed": failed, "data_path": str(data_path), "js_path": str(js_path)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Enriquece portfolio-data con imagenes de Scryfall.")
    parser.add_argument("data", type=Path, nargs="?", default=Path("docs/data/portfolio-data.json"))
    parser.add_argument("--delay", type=float, default=0.12, help="Pausa entre consultas a Scryfall.")
    parser.add_argument("--limit", type=int, default=None, help="Limite opcional de cartas a resolver.")
    args = parser.parse_args()
    result = enrich(args.data, args.delay, args.limit)
    print("Enriquecimiento terminado")
    print(result)


if __name__ == "__main__":
    main()
