#!/usr/bin/env python3
"""Enrich collection JSON with persistent image URLs.

This script is intentionally deterministic: it does not need live HTTP access.
It writes URLs that the static HTML can load later from the browser.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import unicodedata
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
from urllib.parse import quote_plus

SCRYFALL_API = "https://api.scryfall.com/cards"
SCRYFALL_SEARCH = "https://scryfall.com/search"
SCRYDEX_IMAGES = "https://images.scrydex.com/riftbound"
ONEPIECEDB_IMAGES = "https://images.onepiecedb.io/images"

# Manual product/accessory images. These rows are not single MTG cards.
PRODUCT_RULES = [
    {
        "keys": ["unleashed booster box"],
        "source": "riot_product_cdn",
        "confidence": "product_match",
        "normal": "https://cdn.sanity.io/images/dsfx7636/consumer_products_live/46c776a96cc14227a260d24489f10b4090cd2cd9-2560x2560.png?accountingTag=consumer_products",
        "source_url": "https://merch.riotgames.com/en-us/product/riftbound-unleashed-booster-display/",
        "note": "Official Riot product image for the Unleashed Booster Display. Used also for case rows.",
    },
    {
        "keys": ["arcane box set"],
        "source": "riot_product_cdn",
        "confidence": "product_match",
        "normal": "https://cdn.sanity.io/images/dsfx7636/consumer_products_live/2f0e070b2ea935e916cd8fa31253791a37d3a956-2560x2560.png?accountingTag=consumer_products",
        "source_url": "https://merch.riotgames.com/en-us/product/riftbound-arcane-box-set/",
        "note": "Official Riot product image for the Arcane Box Set.",
    },
    {
        "keys": ["worlds bundle"],
        "source": "riot_product_cdn",
        "confidence": "product_match",
        "normal": "https://cdn.sanity.io/images/dsfx7636/consumer_products_live/e67cae02bd6312c1e9a4b3a0eb9e70dbd3dbcd0e-2560x2560.png?accountingTag=consumer_products",
        "source_url": "https://merch.riotgames.com/en-us/product/riftbound-worlds-bundle-2025/",
        "note": "Official Riot product image for the Worlds Bundle 2025.",
    },
    {
        "keys": ["lunar revel bundle playmat", "lunar revel bundle"],
        "source": "riot_product_cdn",
        "confidence": "bundle_representative_image",
        "normal": "https://cdn.sanity.io/images/dsfx7636/consumer_products_live/f09af3a1ceb0a26083f767ce0eb9f6b3254d9752-2560x2560.png?accountingTag=consumer_products",
        "source_url": "https://merch.riotgames.com/en-us/product/riftbound-lunar-revel-bundle-2026/",
        "note": "Official Riot bundle image. The row names the playmat, so this is a representative bundle image rather than an isolated playmat-only image.",
    },
    {
        "keys": ["collector booster box the hobbit"],
        "source": "wizards_product_cdn",
        "confidence": "product_match",
        "normal": "https://media.wizards.com/2026/images/daily/8Bmxd4HQE3/en_GG8zCyKg86.webp",
        "source_url": "https://magic.wizards.com/en/news/feature/collecting-the-hobbit",
        "note": "Wizards product image used for the referenced Collector Booster Box entry.",
    },
    {
        "keys": ["ultra deck: the three brothers", "ultra deck the three brothers"],
        "source": "retailer_thumbnail",
        "confidence": "product_match_retailer_image",
        "normal": "https://cdn.shopify.com/s/files/1/0790/9035/2340/files/st13.jpg?v=1762911565",
        "source_url": "https://en.onepiece-cardgame.com/products/decks/st13.php",
        "note": "Official product identified from One Piece page; image URL is a retailer thumbnail fallback.",
    },
    {
        "keys": ["100 ultra pro platinum nine pocket pages", "ultra pro platinum nine pocket"],
        "source": "ultrapro_product_cdn",
        "confidence": "product_match",
        "normal": "https://ultrapro.com/cdn/shop/files/81320-9Pocket.jpg?v=1783552514&width=160",
        "source_url": "https://ultrapro.com/products/platinum-series-9-pocket-pages-100ct-for-cards-and-photos",
        "note": "Official Ultra PRO product image for Platinum 9-Pocket Pages.",
    },
    {
        "keys": ["mystical archive", "brainstorm", "playmat"],
        "source": "ultrapro_product_cdn",
        "confidence": "product_match",
        "normal": "https://ultrapro.com/cdn/shop/products/18867_AW50332_MAT_MTG_MYST_JPN_12.png?v=1762443630&width=1500",
        "source_url": "https://ultrapro.com/products/japanese-mystical-archive-brainstorm-standard-gaming-playmat-for-magic-the-gathering",
        "note": "Official Ultra PRO product image for the Japanese Mystical Archive Brainstorm playmat.",
    },
    {
        "keys": ["the lord of the rings", "art series set"],
        "source": "scryfall_representative_set_image",
        "confidence": "representative_set_image",
        "normal": "https://api.scryfall.com/cards/altr/425?format=image&version=normal",
        "large": "https://api.scryfall.com/cards/altr/425?format=image&version=large",
        "small": "https://api.scryfall.com/cards/altr/425?format=image&version=small",
        "source_url": "https://scryfall.com/sets/altr",
        "note": "Representative Scryfall image from the Tales of Middle-earth Art Series set, not a sealed product photo.",
    },
]

RIFTBOUND_CARD_CODES = {
    "irelia fervent": "SFD-225",
    "diana scorn of the moon": "UNL-234",
    "leblanc deceiver": "UNL-235",
    "irelia blade dancer": "SFD-246",
    "vex gloomist": "UNL-232",
    "viktor herald of the arcane": "OGN-308",
    "lonely poro": "UNL-221",
    "fiora grand duelist": "SFD-205",
    "viktor leader": "OGN-246",
    "azir emperor of the sands": "SFD-197",
    "baited hook": "OGN-242",
    "vex apathetic": "UNL-150a",
    "last rites": "SFD-150",
    "defiant dance": "SFD-196",
    "arise": "SFD-198",
    "sett brawler": "OGN-164a",
    "moonfall": "UNL-198",
    "elder dragon": "UNL-118a",
    "thousand tailed watcher": "OGN-116",
    "seal of discord": "OGN-204",
}

# A conservative edition-to-set map. When missing, the script uses unscoped
# exact-name endpoints so Scryfall chooses the best available printing.
MTG_SET_CODES = {
    "revised": "3ed",
    "fourth edition black bordered": "4bb",
    "alliances": "all",
    "exodus": "exo",
    "tempest": "tmp",
    "onslaught": "ons",
    "urza s saga": "usg",
    "urza s legacy": "ulg",
    "urza s destiny": "uds",
    "mercadian masques": "mmq",
    "weatherlight": "wth",
    "legends": "leg",
    "torment": "tor",
    "darksteel": "dst",
    "mirrodin besieged": "mbs",
    "scars of mirrodin": "som",
    "new phyrexia": "nph",
    "zendikar rising": "znr",
    "zendikar rising expeditions": "zne",
    "worldwake": "wwk",
    "rise of the eldrazi": "roe",
    "return to ravnica": "rtr",
    "guilds of ravnica": "grn",
    "theros": "ths",
    "theros beyond death": "thb",
    "journey into nyx": "jou",
    "kaladesh": "kld",
    "aether revolt": "aer",
    "battle for zendikar": "bfz",
    "avacyn restored": "avr",
    "innistrad": "isd",
    "eldritch moon": "emn",
    "dominaria": "dom",
    "dominaria united": "dmu",
    "war of the spark": "war",
    "magic the gathering foundations": "fdn",
    "modern horizons": "mh1",
    "modern horizons retro frame cards": "mh1",
    "modern horizons 2": "mh2",
    "modern horizons 2 extras": "mh2",
    "modern horizons 3": "mh3",
    "modern horizons 3 extras": "mh3",
    "double masters": "2xm",
    "double masters 2022 extras": "2x2",
    "eternal masters": "ema",
    "iconic masters": "ima",
    "masters 25": "a25",
    "modern masters 2015": "mm2",
    "khans of tarkir": "ktk",
    "mystical archive": "sta",
    "retro frame artifacts": "brr",
    "the lord of the rings tales of middle earth": "ltr",
    "time spiral": "tsp",
    "time spiral remastered": "tsr",
    "time spiral remastered extras": "tsr",
    "march of the machine the aftermath": "mat",
    "march of the machine extras": "mom",
    "phyrexia all will be one": "one",
    "phyrexia all will be one extras": "one",
    "kamigawa neon dynasty": "neo",
    "kamigawa neon dynasty extras": "neo",
    "kamigawa neon dynasty promos": "pneo",
    "betrayers of kamigawa": "bok",
    "ravnica remastered": "rvr",
    "ravnica remastered extras": "rvr",
    "wilds of eldraine": "woe",
    "duskmourn house of horror extras": "dsk",
    "innistrad remastered": "inr",
    "innistrad remastered extras": "inr",
    "streets of new capenna promos": "psnc",
    "innistrad midnight hunt promos": "pmid",
    "innistrad crimson vow promos": "pvow",
    "core 2021 extras": "m21",
    "magic the gathering final fantasy extras": "fin",
    "aetherdrift extras": "dft",
    "edge of eternities": "eoe",
    "edge of eternities extras": "eoe",
    "tarkir dragonstorm extras": "tdm",
}


def strip_accents(value: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFKD", value) if not unicodedata.combining(ch))


def norm(value: Any) -> str:
    text = strip_accents(str(value or "").lower())
    text = text.replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def clean_card_name(name: str) -> str:
    cleaned = str(name or "").strip()
    cleaned = re.sub(r"\s*\[[^\]]+\]", "", cleaned)
    cleaned = re.sub(r"\s*\(V\.[^)]+\)", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def product_match(card: Dict[str, Any]) -> Optional[Dict[str, str]]:
    blob = norm(" ".join(str(card.get(k, "")) for k in ("name", "cardName", "edition", "tcg")))
    for rule in PRODUCT_RULES:
        if all(norm(key) in blob for key in rule["keys"]):
            return rule
    return None


def image_object(normal: str, source: str, status: str = "resolved", small: Optional[str] = None, large: Optional[str] = None, art: Optional[str] = None) -> Dict[str, str]:
    return {
        "small": small or normal,
        "normal": normal,
        "large": large or normal,
        "artCrop": art or "",
        "status": status,
        "source": source,
    }


def scryfall_named_urls(card_name: str, edition: str) -> Tuple[Dict[str, str], Dict[str, Any]]:
    exact = clean_card_name(card_name)
    set_code = MTG_SET_CODES.get(norm(edition), "")
    exact_q = quote_plus(exact)
    set_suffix = f"&set={quote_plus(set_code)}" if set_code else ""
    def endpoint(version: str) -> str:
        return f"{SCRYFALL_API}/named?exact={exact_q}&format=image&version={version}{set_suffix}"
    images = image_object(
        normal=endpoint("normal"),
        large=endpoint("large"),
        small=endpoint("small"),
        art=endpoint("art_crop"),
        source="scryfall_image_endpoint",
    )
    search_q = f"!\"{exact}\""
    if set_code:
        search_q += f" e:{set_code}"
    info = {
        "resolved": True,
        "method": "named_exact_image_endpoint",
        "queryName": exact,
        "setCode": set_code,
        "imageEndpoint": images["normal"],
        "searchUri": f"{SCRYFALL_SEARCH}?as=grid&order=name&q={quote_plus(search_q)}",
    }
    return images, info


def riftbound_image(card: Dict[str, Any]) -> Optional[Tuple[Dict[str, str], Dict[str, Any]]]:
    cleaned = norm(clean_card_name(str(card.get("cardName") or card.get("name") or "")))
    for key, code in RIFTBOUND_CARD_CODES.items():
        if key in cleaned:
            base = f"{SCRYDEX_IMAGES}/{code}/medium"
            images = image_object(base, "scrydex_image_endpoint")
            info = {
                "resolved": True,
                "method": "scrydex_code_image_endpoint",
                "cardCode": code,
                "imageEndpoint": base,
                "searchUri": f"https://scrydex.com/riftbound/cards/{code}",
            }
            return images, info
    return None


def one_piece_image(card: Dict[str, Any]) -> Optional[Tuple[Dict[str, str], Dict[str, Any]]]:
    name = str(card.get("cardName") or card.get("name") or "")
    match = re.search(r"\b(OP\d{2})-(\d{3})\b", name, flags=re.IGNORECASE)
    if not match:
        return None
    set_code = match.group(1).upper()
    number = match.group(2)
    full_code = f"{set_code}-{number}"
    url = f"{ONEPIECEDB_IMAGES}/{set_code}/{full_code}.png"
    images = image_object(url, "onepiecedb_image_endpoint")
    page_by_code = {
        "OP05-119": "https://onepiecedb.io/card/monkey-d-luffy-op05-119",
        "OP06-118": "https://onepiecedb.io/card/roronoa-zoro-op06-118",
    }
    info = {
        "resolved": True,
        "method": "onepiecedb_card_code_image_endpoint",
        "cardCode": full_code,
        "imageEndpoint": url,
        "searchUri": page_by_code.get(full_code, f"https://onepiecedb.io/search?q={quote_plus(full_code)}"),
    }
    return images, info


def apply_product(card: Dict[str, Any], rule: Dict[str, Any]) -> Tuple[Dict[str, str], Dict[str, Any]]:
    normal = rule["normal"]
    images = image_object(
        normal=normal,
        source=rule["source"],
        small=rule.get("small", normal),
        large=rule.get("large", normal),
        art=rule.get("art", ""),
    )
    info = {
        "resolved": True,
        "method": "manual_product_mapping",
        "matchConfidence": rule.get("confidence", "product_match"),
        "imageEndpoint": normal,
        "sourceUrl": rule.get("source_url", ""),
        "note": rule.get("note", ""),
    }
    return images, info


def enrich(data: Dict[str, Any]) -> Tuple[Dict[str, Any], list[Dict[str, Any]]]:
    now = datetime.now(timezone.utc).isoformat()
    report = []
    stats = Counter()

    for card in data.get("cards", []):
        tcg = str(card.get("tcg") or "")
        name = str(card.get("cardName") or card.get("name") or "")
        edition = str(card.get("edition") or "")
        images = None
        info = None
        status = "pending"
        source = "unresolved"

        rule = product_match(card)
        if rule:
            images, info = apply_product(card, rule)
        elif norm(tcg) == "riftbound":
            result = riftbound_image(card)
            if result:
                images, info = result
        elif norm(tcg) == "one piece":
            result = one_piece_image(card)
            if result:
                images, info = result
        elif norm(tcg) == "magic the gathering":
            images, info = scryfall_named_urls(name, edition)

        if images and info:
            card["images"] = images
            status = images.get("status", "resolved")
            source = images.get("source", "resolved")
            info["status"] = status
            info["resolvedAt"] = now
            card["imageResolution"] = info
            stats["resolved_rows"] += 1
            stats[f"source_{source}"] += 1
            if source == "scryfall_image_endpoint" and not info.get("setCode"):
                stats["scryfall_unscoped_rows"] += 1
            if source == "scryfall_image_endpoint" and info.get("setCode"):
                stats["scryfall_set_scoped_rows"] += 1
            if source.endswith("product_cdn") or source in {"retailer_thumbnail", "scryfall_representative_set_image"}:
                stats["product_or_accessory_rows"] += 1
        else:
            card["images"] = image_object("", "unresolved", status="pending")
            card["imageResolution"] = {
                "resolved": False,
                "status": "pending",
                "method": "unresolved",
                "note": "No deterministic mapping was available.",
                "resolvedAt": now,
            }
            stats["pending_rows"] += 1

        report.append({
            "sourceRow": card.get("sourceRow"),
            "id": card.get("id"),
            "tcg": tcg,
            "name": name,
            "edition": edition,
            "status": card.get("images", {}).get("status", status),
            "source": card.get("images", {}).get("source", source),
            "url": card.get("images", {}).get("normal", ""),
            "method": card.get("imageResolution", {}).get("method", ""),
            "note": card.get("imageResolution", {}).get("note", ""),
        })

    stats["total_rows"] = len(data.get("cards", []))
    stats["pending_rows"] += 0

    data.setdefault("metadata", {})["imageResolution"] = {
        "resolvedRows": int(stats["resolved_rows"]),
        "pendingRows": int(stats["pending_rows"]),
        "totalRows": int(stats["total_rows"]),
        "scryfallEndpointRows": int(stats["source_scryfall_image_endpoint"]),
        "scryfallSetScopedRows": int(stats["scryfall_set_scoped_rows"]),
        "scryfallUnscopedRows": int(stats["scryfall_unscoped_rows"]),
        "scrydexRows": int(stats["source_scrydex_image_endpoint"]),
        "onePieceDbRows": int(stats["source_onepiecedb_image_endpoint"]),
        "manualProductRows": int(stats["product_or_accessory_rows"]),
        "bySource": {k.replace("source_", ""): int(v) for k, v in stats.items() if k.startswith("source_")},
        "resolvedAt": now,
        "strategy": "Scryfall image endpoints for MTG singles; Scrydex for Riftbound singles; OnePieceDB for One Piece singles; manual product mappings for sealed/accessories.",
        "runtimeNote": "The script writes persistent image URLs without requiring live HTTP access in the execution environment.",
    }
    return data, report


def write_outputs(data_path: Path, data: Dict[str, Any], report: list[Dict[str, Any]]) -> None:
    data_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    js_path = data_path.with_suffix(".js")
    js_path.write_text("window.portfolioData = " + json.dumps(data, ensure_ascii=False, indent=2) + ";\n", encoding="utf-8")

    report_json = data_path.parent / "image-resolution-report.json"
    report_json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    report_csv = data_path.parent / "image-resolution-report.csv"
    with report_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["sourceRow", "id", "tcg", "name", "edition", "status", "source", "url", "method", "note"])
        writer.writeheader()
        writer.writerows(report)


def main() -> int:
    parser = argparse.ArgumentParser(description="Enrich portfolio data with persistent image URLs")
    parser.add_argument("json_path", type=Path)
    args = parser.parse_args()
    data = json.loads(args.json_path.read_text(encoding="utf-8"))
    data, report = enrich(data)
    write_outputs(args.json_path, data, report)
    image_stats = data.get("metadata", {}).get("imageResolution", {})
    print(json.dumps(image_stats, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
