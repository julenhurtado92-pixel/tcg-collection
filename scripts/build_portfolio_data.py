#!/usr/bin/env python3
"""Build browser-ready portfolio-data.js from enriched collection JSON."""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def as_float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except Exception:
        return None


def choose_current_price(card: Dict[str, Any], use_scryfall_prices: bool = False) -> Optional[float]:
    if not use_scryfall_prices:
        return None
    prices = card.get("prices") or {}
    foil_text = str(card.get("foiling") or "").lower()
    candidates = []
    if "foil" in foil_text and "nonfoil" not in foil_text:
        candidates = [prices.get("scryfallEurFoil"), prices.get("scryfallEur"), prices.get("scryfallUsdFoil"), prices.get("scryfallUsd")]
    else:
        candidates = [prices.get("scryfallEur"), prices.get("scryfallEurFoil"), prices.get("scryfallUsd"), prices.get("scryfallUsdFoil")]
    for value in candidates:
        parsed = as_float(value)
        if parsed is not None:
            return parsed
    return None


def normalize_status(status: Any) -> str:
    text = str(status or "Holding").strip()
    if not text:
        return "Holding"
    lower = text.lower()
    if "cancel" in lower:
        return "Cancelado"
    if "sold" in lower or "venta" in lower or "vend" in lower:
        return "Sold"
    if "watch" in lower or "wish" in lower or "segu" in lower:
        return "Watchlist"
    return text


def build_card(row: Dict[str, Any], use_scryfall_prices: bool = False) -> Dict[str, Any]:
    scryfall = row.get("scryfall") or {}
    image_urls = row.get("image") or {}
    normal_image = image_urls.get("normal") or image_urls.get("large") or image_urls.get("small") or image_urls.get("png")
    qty = int(row.get("quantity") or 0)
    buy_price = as_float(row.get("buyPrice"))
    total_buy = as_float(row.get("totalBuyPrice"))
    if total_buy is None and buy_price is not None:
        total_buy = round(buy_price * qty, 4)
    current_price = choose_current_price(row, use_scryfall_prices=use_scryfall_prices)
    status = normalize_status(row.get("status"))
    set_name = scryfall.get("setName") or row.get("edition") or row.get("setCode") or "Unknown"
    set_code = scryfall.get("set") or row.get("setCode")
    card_number = scryfall.get("collectorNumber") or row.get("collectorNumber")
    card = {
        "id": row.get("internalId") or scryfall.get("id"),
        "name": row.get("cardName") or scryfall.get("name"),
        "lookupName": row.get("lookupName") or row.get("cardName") or scryfall.get("name"),
        "set": set_name,
        "setCode": set_code,
        "condition": row.get("condition") or "EX",
        "language": row.get("language"),
        "tcg": row.get("tcg"),
        "status": status,
        "qty": qty,
        "buyPrice": buy_price,
        "totalBuyPrice": total_buy,
        "currentPrice": current_price,
        "image": normal_image,
        "imageUrls": image_urls,
        "cardNumber": card_number,
        "foiling": row.get("foiling"),
        "operationType": row.get("operationType"),
        "date": row.get("date"),
        "cardmarketUrl": row.get("cardmarketUrl"),
        "scryfallUrl": scryfall.get("uri") or row.get("scryfallUrl"),
        "scryfall": scryfall,
        "prices": row.get("prices") or {},
        "priceHistory": row.get("priceHistory") or [],
        "needsReview": bool(row.get("needsReview")),
        "source": row.get("source") or {},
        "notes": row.get("notes"),
    }
    if current_price is not None and buy_price is not None:
        card["pnl"] = round((current_price - buy_price) * qty, 4)
        card["pnlPct"] = round(((current_price - buy_price) / buy_price) * 100, 2) if buy_price else None
    else:
        card["pnl"] = None
        card["pnlPct"] = None
    return card


def build_summary(cards: List[Dict[str, Any]]) -> Dict[str, Any]:
    active = [c for c in cards if c.get("status") not in {"Cancelado", "Sold"}]
    with_market = [c for c in active if c.get("currentPrice") is not None]
    invested = sum((c.get("totalBuyPrice") or 0) for c in active)
    market_value = sum((c.get("currentPrice") or 0) * (c.get("qty") or 0) for c in active)
    return {
        "cardsTotal": sum(c.get("qty") or 0 for c in active),
        "rowsTotal": len(cards),
        "activeRows": len(active),
        "invested": round(invested, 2),
        "marketValue": round(market_value, 2) if with_market else None,
        "pnl": round(market_value - invested, 2) if with_market else None,
        "withMarketPrice": len(with_market),
        "needsReview": sum(1 for c in cards if c.get("needsReview")),
        "missingImages": sum(1 for c in cards if not c.get("image")),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate portfolio-data.js for the dashboard")
    parser.add_argument("--input", default="data/collection.enriched.json")
    parser.add_argument("--out-js", default="public/data/portfolio-data.js")
    parser.add_argument("--out-json", default="public/data/portfolio-data.json")
    parser.add_argument("--base-dir", default=".")
    parser.add_argument("--use-scryfall-prices", action="store_true", help="Use Scryfall EUR/USD price fields as temporary market prices")
    args = parser.parse_args()

    base_dir = Path(args.base_dir).resolve()
    source = load_json(base_dir / args.input)
    cards = [build_card(row, use_scryfall_prices=args.use_scryfall_prices) for row in source.get("cards", [])]
    payload = {
        "schemaVersion": "0.1.0",
        "updatedAt": datetime.now().astimezone().isoformat(timespec="seconds"),
        "source": source.get("source", {}),
        "enrichment": source.get("enrichment", {}),
        "summary": build_summary(cards),
        "cards": cards,
    }

    json_path = base_dir / args.out_json
    js_path = base_dir / args.out_js
    save_json(json_path, payload)
    js_path.parent.mkdir(parents=True, exist_ok=True)
    js_text = "// Generated file. Do not edit by hand.\nwindow.portfolioData = " + json.dumps(payload, ensure_ascii=False, indent=2) + ";\n"
    js_path.write_text(js_text, encoding="utf-8")
    print(f"Wrote {js_path}")
    print(f"Wrote {json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
