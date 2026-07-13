#!/usr/bin/env python3
"""
Actualiza precios de mercado usando las tablas publicas de Cardmarket.

No scrapea paginas de producto una a una. Descarga los JSON oficiales de
Product Catalog y Price Guides, cruza productos por nombre/TCG/edicion/variante
y persiste los precios en docs/data/market-prices.* y, opcionalmente, dentro de
portfolio-data.* y wishlist-data.*.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sys
import time
import unicodedata
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

BASE_DOWNLOAD = "https://downloads.s3.cardmarket.com/productCatalog"

GAMES: Dict[str, Dict[str, Any]] = {
    "magic": {
        "id": 1,
        "cardmarket_path": "Magic",
        "labels": ["magic", "magic the gathering", "magic: the gathering", "mtg"],
        "tcg_label": "Magic The Gathering",
    },
    "onepiece": {
        "id": 18,
        "cardmarket_path": "OnePiece",
        "labels": ["one piece", "onepiece", "one piece tcg"],
        "tcg_label": "One Piece",
    },
    "riftbound": {
        "id": 22,
        "cardmarket_path": "Riftbound",
        "labels": ["riftbound", "league of legends"],
        "tcg_label": "Riftbound",
    },
    "accessories": {
        "id": "accessories",
        "cardmarket_path": "Accessories",
        "labels": ["accessories", "accessory", "accesorios", "accesorio", "ultra pro"],
        "tcg_label": "Accesorios",
    },
}

SEALED_KEYWORDS = [
    "booster", "display", "box", "bundle", "commander deck", "starter deck", "deck",
    "collector", "case", "playmat", "sleeves", "deck box", "sealed", "pack", "kit",
    "sobre", "sobres", "caja", "accesorio", "accessory", "full set", "set",
]

# Sinopsis de campos encontrados en price guides de Cardmarket y en wrappers comunes.
PRICE_FIELDS = {
    "normal": {
        "sell": ["sellPrice", "sell", "from", "fromPrice", "price", "min", "minPrice"],
        "low": ["lowPrice", "low", "lowest", "lowestPrice", "minimum", "sellPrice"],
        "trend": ["trendPrice", "trend", "priceTrend"],
        "avg": ["averageSellPrice", "avg", "average", "avgPrice", "averagePrice"],
        "avg1": ["avg1", "avg1Price", "average1", "oneDayAverage", "averageOneDay"],
        "avg7": ["avg7", "avg7Price", "average7", "sevenDayAverage", "averageSevenDays"],
        "avg30": ["avg30", "avg30Price", "average30", "thirtyDayAverage", "averageThirtyDays"],
    },
    "foil": {
        "sell": ["foilSell", "foilSellPrice", "foilFrom", "foilFromPrice", "foilPrice"],
        "low": ["foilLow", "foilLowPrice", "foilLowest", "foilLowestPrice", "foilSell"],
        "trend": ["foilTrend", "foilTrendPrice", "foilPriceTrend"],
        "avg": ["foilAverageSellPrice", "foilAvg", "foilAverage", "foilAvgPrice"],
        "avg1": ["foilAvg1", "foilAvg1Price", "foilAverage1", "foilOneDayAverage"],
        "avg7": ["foilAvg7", "foilAvg7Price", "foilAverage7", "foilSevenDayAverage"],
        "avg30": ["foilAvg30", "foilAvg30Price", "foilAverage30", "foilThirtyDayAverage"],
    },
}

PREFERRED_PRICE_ORDER = ["trend", "avg30", "avg7", "avg1", "avg", "low", "sell"]


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def text(value: Any) -> str:
    return str(value or "").strip()


def strip_accents(value: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFD", value) if unicodedata.category(ch) != "Mn")


def normalize(value: Any) -> str:
    raw = strip_accents(text(value)).lower()
    raw = raw.replace("&", " and ")
    raw = re.sub(r"\bthe\b", " ", raw)
    raw = re.sub(r"[^a-z0-9]+", " ", raw)
    return re.sub(r"\s+", " ", raw).strip()


def norm_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", strip_accents(text(value)).lower())


def tokens(value: Any) -> set[str]:
    return {tok for tok in normalize(value).split() if tok}


def to_number(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        return round(float(value), 2)
    raw = text(value)
    if not raw:
        return None
    # Permite formatos europeos y strings con moneda.
    raw = re.sub(r"[^0-9,.-]", "", raw)
    if raw.count(",") == 1 and raw.count(".") > 0 and raw.rfind(",") > raw.rfind("."):
        raw = raw.replace(".", "").replace(",", ".")
    elif raw.count(",") == 1 and raw.count(".") == 0:
        raw = raw.replace(",", ".")
    try:
        number = float(raw)
    except ValueError:
        return None
    if not math.isfinite(number):
        return None
    return round(number, 2)


def round_money(value: Any) -> Optional[float]:
    number = to_number(value)
    return None if number is None else round(number + 1e-9, 2)


def is_foil(variant: Any) -> bool:
    normalized = normalize(variant)
    return "foil" in normalized and "non foil" not in normalized and "nonfoil" not in normalized


def is_sealed_item(item: Dict[str, Any]) -> bool:
    haystack = normalize(f"{item.get('cardName') or item.get('name')} {item.get('edition')} {item.get('categoryName')}")
    return any(keyword in haystack for keyword in SEALED_KEYWORDS)


def game_slug_for_tcg(tcg: Any, item: Optional[Dict[str, Any]] = None) -> str:
    normalized = normalize(tcg)
    for slug, info in GAMES.items():
        if any(normalize(label) in normalized for label in info["labels"]):
            return slug
    if item and is_sealed_item(item):
        # La mayoria de sellado conserva el TCG real. Accessories se usa como pool adicional, no como default.
        return "magic" if "magic" in normalized else "accessories"
    return normalized or "unknown"


def official_urls_for_game(slug: str) -> Dict[str, str]:
    info = GAMES[slug]
    gid = info["id"]
    if slug == "accessories":
        return {
            "products_accessories": f"{BASE_DOWNLOAD}/productList/products_accessories.json",
            "price_guide": f"{BASE_DOWNLOAD}/priceGuide/price_guide_accessories.json",
        }
    return {
        "products_singles": f"{BASE_DOWNLOAD}/productList/products_singles_{gid}.json",
        "products_nonsingles": f"{BASE_DOWNLOAD}/productList/products_nonsingles_{gid}.json",
        "price_guide": f"{BASE_DOWNLOAD}/priceGuide/price_guide_{gid}.json",
    }


def load_json(path: Path, fallback: Any) -> Any:
    if not path.exists():
        return fallback
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def save_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
        fh.write("\n")


def save_js(path: Path, global_name: str, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        fh.write(f"window.{global_name} = ")
        json.dump(payload, fh, ensure_ascii=False, indent=2)
        fh.write(";\n")


def download_json(url: str, cache_path: Path, *, force: bool = False, sleep: float = 0.2) -> Any:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    if cache_path.exists() and not force:
        return load_json(cache_path, {})
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "TCG-Collection-Price-Updater/1.0 (+local personal collection)",
            "Accept": "application/json,text/json,*/*",
        },
    )
    with urllib.request.urlopen(request, timeout=90) as response:
        raw = response.read().decode("utf-8-sig")
    payload = json.loads(raw)
    save_json(cache_path, payload)
    if sleep:
        time.sleep(sleep)
    return payload


def recursive_lists_with_idproduct(payload: Any) -> List[Dict[str, Any]]:
    found: List[Dict[str, Any]] = []
    if isinstance(payload, list):
        if payload and all(isinstance(item, dict) for item in payload):
            if any("idProduct" in item or "idproduct" in {k.lower() for k in item.keys()} for item in payload):
                return list(payload)
        for item in payload:
            found.extend(recursive_lists_with_idproduct(item))
    elif isinstance(payload, dict):
        for preferred in ["products", "prices", "priceGuides", "priceGuide", "data", "items", "results"]:
            value = payload.get(preferred)
            if isinstance(value, list) and value and all(isinstance(item, dict) for item in value):
                if any(key.lower() == "idproduct" for key in value[0].keys()):
                    return list(value)
        for value in payload.values():
            found.extend(recursive_lists_with_idproduct(value))
    return found


def get_case_insensitive(obj: Dict[str, Any], key: str, default: Any = None) -> Any:
    wanted = key.lower()
    for current, value in obj.items():
        if current.lower() == wanted:
            return value
    return default


def lower_key_map(obj: Dict[str, Any]) -> Dict[str, Any]:
    return {norm_key(k): v for k, v in obj.items()}


def first_numeric(obj: Dict[str, Any], candidate_names: Iterable[str]) -> Optional[float]:
    lookup = lower_key_map(obj)
    for name in candidate_names:
        value = lookup.get(norm_key(name))
        number = to_number(value)
        if number is not None:
            return number
    return None


def price_values(price_entry: Dict[str, Any], variant: Any) -> Tuple[Dict[str, Optional[float]], str]:
    foil = is_foil(variant)
    mode = "foil" if foil else "normal"
    values = {key: first_numeric(price_entry, fields) for key, fields in PRICE_FIELDS[mode].items()}
    fallback_used = "none"
    if foil and not any(value is not None for value in values.values()):
        values = {key: first_numeric(price_entry, fields) for key, fields in PRICE_FIELDS["normal"].items()}
        fallback_used = "foil_to_normal"
    return values, fallback_used


def selected_price(values: Dict[str, Optional[float]]) -> Tuple[Optional[float], Optional[str]]:
    for key in PREFERRED_PRICE_ORDER:
        value = values.get(key)
        if value is not None:
            return round_money(value), key
    return None, None


def product_url(slug: str, product: Any) -> str:
    name = text(product.name if hasattr(product, "name") else product.get("name"))
    # URL de busqueda estable: evita depender del slug exacto del producto.
    game_path = GAMES.get(slug, {}).get("cardmarket_path", "Magic")
    from urllib.parse import quote_plus
    return f"https://www.cardmarket.com/en/{game_path}/Products/Search?searchString={quote_plus(name)}"


@dataclass
class CatalogProduct:
    id_product: int
    name: str
    game_slug: str
    product_kind: str
    category_name: str = ""
    id_expansion: str = ""
    expansion_name: str = ""
    raw: Dict[str, Any] = field(default_factory=dict)
    price: Dict[str, Any] = field(default_factory=dict)

    @property
    def normalized_name(self) -> str:
        return normalize(self.name)

    @property
    def normalized_expansion(self) -> str:
        return normalize(self.expansion_name or self.raw.get("expansion") or self.raw.get("setName") or "")


def extract_expansion_name(obj: Dict[str, Any]) -> str:
    for key in ["expansionName", "expansion", "setName", "set", "edition", "expansionTitle"]:
        value = text(obj.get(key))
        if value:
            return value
    return ""


class CardmarketCatalog:
    def __init__(self) -> None:
        self.products_by_game: Dict[str, List[CatalogProduct]] = {slug: [] for slug in GAMES}
        self.products_by_id: Dict[int, CatalogProduct] = {}
        self.price_by_id: Dict[int, Dict[str, Any]] = {}
        self.downloaded: Dict[str, Any] = {}

    def add_prices(self, payload: Any) -> None:
        for entry in recursive_lists_with_idproduct(payload):
            raw_id = get_case_insensitive(entry, "idProduct")
            try:
                id_product = int(raw_id)
            except (TypeError, ValueError):
                continue
            self.price_by_id[id_product] = entry

    def add_products(self, slug: str, kind: str, payload: Any) -> None:
        for entry in recursive_lists_with_idproduct(payload):
            raw_id = get_case_insensitive(entry, "idProduct")
            try:
                id_product = int(raw_id)
            except (TypeError, ValueError):
                continue
            product = CatalogProduct(
                id_product=id_product,
                name=text(entry.get("name")),
                game_slug=slug,
                product_kind=kind,
                category_name=text(entry.get("categoryName")),
                id_expansion=text(entry.get("idExpansion")),
                expansion_name=extract_expansion_name(entry),
                raw=entry,
            )
            existing = self.products_by_id.get(id_product)
            if existing:
                # Mantiene el primer producto, pero completa datos si el segundo trae expansion.
                if not existing.expansion_name and product.expansion_name:
                    existing.expansion_name = product.expansion_name
                continue
            self.products_by_game.setdefault(slug, []).append(product)
            self.products_by_id[id_product] = product

    def attach_prices(self) -> None:
        for id_product, product in self.products_by_id.items():
            product.price = self.price_by_id.get(id_product, {})
            if product.price and not product.expansion_name:
                product.expansion_name = extract_expansion_name(product.price)


def load_cardmarket_catalog(slugs: Iterable[str], cache_dir: Path, force_download: bool = False) -> CardmarketCatalog:
    catalog = CardmarketCatalog()
    for slug in slugs:
        if slug not in GAMES:
            continue
        urls = official_urls_for_game(slug)
        for label, url in urls.items():
            cache_path = cache_dir / f"{label}_{slug}.json"
            payload = download_json(url, cache_path, force=force_download)
            catalog.downloaded[f"{slug}:{label}"] = {"url": url, "cache": str(cache_path)}
            if label == "price_guide":
                catalog.add_prices(payload)
            else:
                kind = "accessory" if "accessories" in label else ("single" if "singles" in label and "nonsingles" not in label else "nonsingle")
                catalog.add_products(slug, kind, payload)
    catalog.attach_prices()
    return catalog


def token_overlap_score(a: str, b: str) -> float:
    at = tokens(a)
    bt = tokens(b)
    if not at or not bt:
        return 0.0
    return len(at & bt) / max(len(at), len(bt))


def name_similarity(item_name: str, product_name: str) -> float:
    a = normalize(item_name)
    b = normalize(product_name)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    seq = SequenceMatcher(None, a, b).ratio()
    overlap = token_overlap_score(a, b)
    contains = 0.92 if a in b or b in a else 0.0
    # Penaliza productos muy largos que solo contienen el nombre de la carta como parte del texto.
    length_penalty = min(len(a), len(b)) / max(len(a), len(b))
    return max(seq, overlap * 0.94, contains * (0.82 + 0.18 * length_penalty))


def edition_similarity(item_edition: str, product: CatalogProduct) -> Optional[float]:
    expansion = product.expansion_name
    if not text(expansion):
        return None
    a = normalize(item_edition)
    b = normalize(expansion)
    if not a or not b:
        return None
    if a == b or a in b or b in a:
        return 1.0
    # Algunas ediciones del Excel incluyen ": Extras".
    a_base = normalize(re.sub(r"\bextras?\b", "", item_edition, flags=re.I))
    if a_base and (a_base == b or a_base in b or b in a_base):
        return 0.95
    return SequenceMatcher(None, a, b).ratio()


def has_price_for_variant(product: CatalogProduct, variant: Any) -> bool:
    values, fallback = price_values(product.price, variant)
    return any(value is not None for value in values.values()) and not (is_foil(variant) and fallback == "foil_to_normal")


def candidate_score(item: Dict[str, Any], product: CatalogProduct) -> Tuple[float, List[str]]:
    item_name = text(item.get("cardName") or item.get("name"))
    item_edition = text(item.get("edition"))
    name_sim = name_similarity(item_name, product.name)
    score = name_sim * 64
    reasons = [f"nombre={round(name_sim * 100)}"]

    sealed = is_sealed_item(item)
    if sealed and product.product_kind in {"nonsingle", "accessory"}:
        score += 12
        reasons.append("tipo=sellado")
    elif not sealed and product.product_kind == "single":
        score += 10
        reasons.append("tipo=single")
    elif sealed and product.product_kind == "single":
        score -= 16
        reasons.append("penaliza_single")

    ed_sim = edition_similarity(item_edition, product)
    if ed_sim is not None:
        score += ed_sim * 16
        reasons.append(f"edicion={round(ed_sim * 100)}")
    elif item_edition and normalize(item_edition) in normalize(product.name):
        score += 8
        reasons.append("edicion_en_nombre")

    if product.price:
        score += 6
        reasons.append("con_priceguide")
    if has_price_for_variant(product, item.get("variant")):
        score += 6
        reasons.append("precio_variante")

    category = normalize(product.category_name)
    if sealed and any(keyword in category for keyword in SEALED_KEYWORDS):
        score += 4
        reasons.append("categoria_sellado")

    if name_sim < 0.56:
        score -= 24
    return round(score, 2), reasons


def market_price_payload(item: Dict[str, Any], product: CatalogProduct, score: float, status: str, reason: str) -> Dict[str, Any]:
    values, fallback = price_values(product.price, item.get("variant"))
    selected, selected_label = selected_price(values)
    resolved_at = now_iso()
    product_payload = {
        "idProduct": product.id_product,
        "name": product.name,
        "categoryName": product.category_name,
        "idExpansion": product.id_expansion,
        "expansionName": product.expansion_name,
        "game": product.game_slug,
        "kind": product.product_kind,
        "url": product_url(product.game_slug, product),
    }
    return {
        "status": status,
        "source": "Cardmarket Data Tables",
        "currency": "EUR",
        "unit": selected,
        "selected": selected,
        "selectedLabel": selected_label,
        "sell": values.get("sell"),
        "low": values.get("low"),
        "trend": values.get("trend"),
        "avg": values.get("avg"),
        "avg1": values.get("avg1"),
        "avg7": values.get("avg7"),
        "avg30": values.get("avg30"),
        "productId": product.id_product,
        "productName": product.name,
        "productUrl": product_payload["url"],
        "productKind": product.product_kind,
        "categoryName": product.category_name,
        "matchConfidence": round(score, 2),
        "matchReason": reason,
        "variantFallback": fallback,
        "lastUpdated": resolved_at,
        "cardmarket": product_payload,
    }


def empty_market_payload(status: str, reason: str, candidates: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    return {
        "status": status,
        "source": "Cardmarket Data Tables",
        "currency": "EUR",
        "unit": None,
        "selected": None,
        "selectedLabel": None,
        "sell": None,
        "low": None,
        "trend": None,
        "avg": None,
        "avg1": None,
        "avg7": None,
        "avg30": None,
        "productId": None,
        "productName": None,
        "productUrl": None,
        "productKind": None,
        "categoryName": None,
        "matchConfidence": 0,
        "matchReason": reason,
        "lastUpdated": now_iso(),
        "candidates": candidates or [],
    }


def candidate_to_report(product: CatalogProduct, score: float, reasons: List[str]) -> Dict[str, Any]:
    selected, selected_label = selected_price(price_values(product.price, "Non-foil")[0])
    foil_selected, foil_label = selected_price(price_values(product.price, "Foil")[0])
    return {
        "idProduct": product.id_product,
        "name": product.name,
        "game": product.game_slug,
        "kind": product.product_kind,
        "categoryName": product.category_name,
        "idExpansion": product.id_expansion,
        "expansionName": product.expansion_name,
        "score": score,
        "reasons": ";".join(reasons),
        "price": selected,
        "priceLabel": selected_label,
        "foilPrice": foil_selected,
        "foilPriceLabel": foil_label,
        "url": product_url(product.game_slug, product),
    }


def get_override(overrides: Dict[str, Any], item_id: str, wishlist: bool = False) -> Dict[str, Any]:
    section = "wishlistItems" if wishlist else "items"
    data = overrides.get(section, {}) if isinstance(overrides, dict) else {}
    value = data.get(item_id, {})
    return value if isinstance(value, dict) else {}


def match_item(
    item: Dict[str, Any],
    catalog: CardmarketCatalog,
    overrides: Dict[str, Any],
    *,
    min_confidence: float,
    wishlist: bool = False,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    item_id = text(item.get("id"))
    override = get_override(overrides, item_id, wishlist=wishlist)
    override_id = override.get("idProduct") or override.get("productId")
    if override_id:
        try:
            product = catalog.products_by_id[int(override_id)]
        except (KeyError, TypeError, ValueError):
            market = empty_market_payload("unmatched", f"override_idProduct_no_encontrado:{override_id}")
            return market, []
        score, reasons = candidate_score(item, product)
        market = market_price_payload(item, product, max(score, 100), "resolved", "override_manual")
        if not market["unit"]:
            market["status"] = "unmatched"
            market["matchReason"] = "override_sin_precio"
        return market, [candidate_to_report(product, max(score, 100), reasons + ["override"])]

    slug = game_slug_for_tcg(item.get("tcg"), item)
    candidate_pools: List[CatalogProduct] = []
    if slug in catalog.products_by_game:
        candidate_pools.extend(catalog.products_by_game.get(slug, []))
    # Accessories como pool adicional para productos que parezcan accesorios.
    if is_sealed_item(item) and slug != "accessories":
        candidate_pools.extend(catalog.products_by_game.get("accessories", []))

    scored: List[Tuple[float, CatalogProduct, List[str]]] = []
    for product in candidate_pools:
        score, reasons = candidate_score(item, product)
        if score >= 25:
            scored.append((score, product, reasons))
    scored.sort(key=lambda row: row[0], reverse=True)
    top = scored[:8]
    candidate_reports = [candidate_to_report(product, score, reasons) for score, product, reasons in top]
    if not top:
        return empty_market_payload("unmatched", "sin_candidatos"), []

    best_score, best_product, best_reasons = top[0]
    second_score = top[1][0] if len(top) > 1 else -1
    has_price = bool(best_product.price)
    values, _fallback = price_values(best_product.price, item.get("variant"))
    has_selected_price = selected_price(values)[0] is not None

    if not has_price or not has_selected_price:
        return empty_market_payload("unmatched", "candidato_sin_priceguide", candidate_reports), candidate_reports

    # Ambiguo cuando la segunda opcion esta muy cerca o comparte nombre exacto sin expansion clara.
    best_name = normalize(best_product.name)
    second_same_name = len(top) > 1 and normalize(top[1][1].name) == best_name
    no_expansion_signal = not best_product.expansion_name
    if best_score < min_confidence:
        status = "unmatched"
        reason = "confianza_baja"
    elif second_score >= best_score - 3 and (second_same_name or no_expansion_signal):
        status = "ambiguous"
        reason = "varios_candidatos_similares"
    else:
        status = "resolved"
        reason = ";".join(best_reasons)

    market = market_price_payload(item, best_product, best_score, status, reason)
    if status != "resolved":
        market["candidates"] = candidate_reports
    return market, candidate_reports


def update_collection_items(
    items: List[Dict[str, Any]],
    catalog: CardmarketCatalog,
    overrides: Dict[str, Any],
    *,
    min_confidence: float,
    wishlist: bool = False,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    price_items: List[Dict[str, Any]] = []
    updated_items: List[Dict[str, Any]] = []
    report_rows: List[Dict[str, Any]] = []

    for item in items:
        item_id = text(item.get("id"))
        market, candidates = match_item(item, catalog, overrides, min_confidence=min_confidence, wishlist=wishlist)
        quantity = to_number(item.get("quantity")) or 0
        unit_cost = to_number(item.get("unitPurchaseValue") or item.get("unitPrice")) or 0
        market_unit = to_number(market.get("unit"))
        market_total = round((market_unit or 0) * quantity, 2) if market_unit is not None else None
        cost_total = round(unit_cost * quantity, 2)
        delta_total = round(market_total - cost_total, 2) if market_total is not None else None
        recovery = round((market_unit / unit_cost) * 100, 2) if market_unit is not None and unit_cost else None

        market["quantity"] = quantity
        market["costUnit"] = round(unit_cost, 2)
        market["marketTotal"] = market_total
        market["costTotal"] = cost_total
        market["deltaTotal"] = delta_total
        market["recoveryRate"] = recovery

        price_item = {
            "itemId": item_id,
            "scope": "wishlist" if wishlist else "collection",
            "tcg": text(item.get("tcg")),
            "name": text(item.get("cardName") or item.get("name")),
            "edition": text(item.get("edition")),
            "language": text(item.get("language")),
            "variant": text(item.get("variant")),
            "quantity": quantity,
            "unitPurchaseValue": unit_cost,
            "marketPrice": market,
        }
        price_items.append(price_item)

        updated = dict(item)
        updated["marketPrice"] = market
        updated_items.append(updated)

        report_row = {
            "scope": "wishlist" if wishlist else "collection",
            "itemId": item_id,
            "tcg": price_item["tcg"],
            "name": price_item["name"],
            "edition": price_item["edition"],
            "language": price_item["language"],
            "variant": price_item["variant"],
            "quantity": quantity,
            "unitPurchaseValue": unit_cost,
            "status": market.get("status"),
            "marketUnit": market.get("unit"),
            "marketTotal": market_total,
            "deltaTotal": delta_total,
            "recoveryRate": recovery,
            "matchConfidence": market.get("matchConfidence"),
            "matchReason": market.get("matchReason"),
            "productId": market.get("productId"),
            "productName": market.get("productName"),
            "productKind": market.get("productKind"),
            "categoryName": market.get("categoryName"),
            "productUrl": market.get("productUrl"),
        }
        for idx, candidate in enumerate(candidates[:5], start=1):
            prefix = f"candidate{idx}"
            report_row[f"{prefix}Id"] = candidate.get("idProduct")
            report_row[f"{prefix}Name"] = candidate.get("name")
            report_row[f"{prefix}Score"] = candidate.get("score")
            report_row[f"{prefix}Price"] = candidate.get("price")
            report_row[f"{prefix}FoilPrice"] = candidate.get("foilPrice")
            report_row[f"{prefix}Url"] = candidate.get("url")
        report_rows.append(report_row)

    return price_items, updated_items, report_rows


def summary_for(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    status_counts: Dict[str, int] = {}
    value = 0.0
    cost = 0.0
    for item in items:
        market = item.get("marketPrice", {})
        status = text(market.get("status") or "not_requested")
        status_counts[status] = status_counts.get(status, 0) + 1
        value += to_number(market.get("marketTotal")) or 0
        cost += to_number(market.get("costTotal")) or 0
    return {
        "totalItems": len(items),
        "resolved": status_counts.get("resolved", 0),
        "ambiguous": status_counts.get("ambiguous", 0),
        "unmatched": status_counts.get("unmatched", 0),
        "notRequested": status_counts.get("not_requested", 0),
        "marketValue": round(value, 2),
        "costValue": round(cost, 2),
        "deltaValue": round(value - cost, 2),
        "recoveryRate": round((value / cost) * 100, 2) if cost else None,
        "statusCounts": status_counts,
    }


def write_report_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames: List[str] = []
    for row in rows:
        for key in row.keys():
            if key not in fieldnames:
                fieldnames.append(key)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def ensure_override_file(path: Path) -> None:
    if path.exists():
        return
    save_json(path, {
        "metadata": {
            "description": "Mapeos manuales por itemId a idProduct de Cardmarket. Usar cuando el reporte devuelva ambiguous/unmatched.",
        },
        "items": {},
        "wishlistItems": {},
    })


def update_portfolio_payload(portfolio: Dict[str, Any], updated_cards: List[Dict[str, Any]], market_summary: Dict[str, Any]) -> Dict[str, Any]:
    payload = dict(portfolio)
    payload["cards"] = updated_cards
    metadata = dict(payload.get("metadata") or {})
    metadata["marketPrices"] = {
        "source": "Cardmarket Data Tables",
        "generatedAt": now_iso(),
        "summary": market_summary,
    }
    payload["metadata"] = metadata
    return payload


def update_wishlist_payload(wishlist: Dict[str, Any], updated_items: List[Dict[str, Any]], market_summary: Dict[str, Any]) -> Dict[str, Any]:
    payload = dict(wishlist)
    payload["items"] = updated_items
    metadata = dict(payload.get("metadata") or {})
    metadata["marketPrices"] = {
        "source": "Cardmarket Data Tables",
        "generatedAt": now_iso(),
        "summary": market_summary,
    }
    payload["metadata"] = metadata
    return payload


def games_from_data(portfolio: Dict[str, Any], wishlist: Dict[str, Any], extra_games: Iterable[str]) -> List[str]:
    slugs = set(extra_games)
    for item in list(portfolio.get("cards") or []) + list(wishlist.get("items") or []):
        slug = game_slug_for_tcg(item.get("tcg"), item)
        if slug in GAMES:
            slugs.add(slug)
        if is_sealed_item(item):
            slugs.add("accessories")
    # Incluye los TCGs objetivo siempre para tener el universo completo de la coleccion.
    slugs.update(["magic", "onepiece", "riftbound"])
    return [slug for slug in ["magic", "onepiece", "riftbound", "accessories"] if slug in slugs]


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Actualiza precios con Cardmarket Data Tables.")
    parser.add_argument("--portfolio", default="docs/data/portfolio-data.json", help="Ruta a portfolio-data.json")
    parser.add_argument("--wishlist", default="docs/data/wishlist-data.json", help="Ruta a wishlist-data.json")
    parser.add_argument("--out", default="docs/data", help="Carpeta de salida")
    parser.add_argument("--cache", default=".cache/cardmarket", help="Carpeta de cache de descargas")
    parser.add_argument("--overrides", default="docs/data/cardmarket-overrides.json", help="Mapeos manuales itemId -> idProduct")
    parser.add_argument("--min-confidence", type=float, default=72.0, help="Confianza minima para marcar como resuelto")
    parser.add_argument("--force-download", action="store_true", help="Redescarga las tablas aunque exista cache")
    parser.add_argument("--update-portfolio", action="store_true", help="Actualiza portfolio-data.json/js con marketPrice")
    parser.add_argument("--update-wishlist", action="store_true", help="Actualiza wishlist-data.json/js con marketPrice")
    parser.add_argument("--games", default="", help="Lista opcional de slugs separada por comas: magic,onepiece,riftbound,accessories")
    args = parser.parse_args(argv)

    portfolio_path = Path(args.portfolio)
    wishlist_path = Path(args.wishlist)
    out_dir = Path(args.out)
    cache_dir = Path(args.cache)
    overrides_path = Path(args.overrides)

    portfolio = load_json(portfolio_path, {"metadata": {}, "cards": []})
    wishlist = load_json(wishlist_path, {"metadata": {}, "items": []})
    ensure_override_file(overrides_path)
    overrides = load_json(overrides_path, {"items": {}, "wishlistItems": {}})

    extra_games = [normalize(part).replace(" ", "") for part in args.games.split(",") if part.strip()]
    slugs = games_from_data(portfolio, wishlist, extra_games)
    print(f"Descargando tablas Cardmarket para: {', '.join(slugs)}")
    catalog = load_cardmarket_catalog(slugs, cache_dir, force_download=args.force_download)
    print(f"Productos cargados: {len(catalog.products_by_id):,}; price guide: {len(catalog.price_by_id):,}")

    price_items, updated_cards, report_collection = update_collection_items(
        list(portfolio.get("cards") or []), catalog, overrides, min_confidence=args.min_confidence, wishlist=False
    )
    wishlist_price_items, updated_wishlist_items, report_wishlist = update_collection_items(
        list(wishlist.get("items") or []), catalog, overrides, min_confidence=args.min_confidence, wishlist=True
    )

    market_summary = summary_for(price_items)
    wishlist_summary = summary_for(wishlist_price_items)
    market_payload = {
        "metadata": {
            "source": "Cardmarket Data Tables",
            "generatedAt": now_iso(),
            "downloaded": catalog.downloaded,
            "minConfidence": args.min_confidence,
            "note": "Precios diarios agregados de Cardmarket. Revisar ambiguous/unmatched antes de tomar decisiones de venta.",
        },
        "items": price_items,
        "wishlistItems": wishlist_price_items,
        "summary": market_summary,
        "wishlistSummary": wishlist_summary,
    }

    save_json(out_dir / "market-prices.json", market_payload)
    save_js(out_dir / "market-prices.js", "marketPricesData", market_payload)

    report_rows = report_collection + report_wishlist
    save_json(out_dir / "cardmarket-matching-report.json", {
        "metadata": market_payload["metadata"],
        "summary": market_summary,
        "wishlistSummary": wishlist_summary,
        "rows": report_rows,
    })
    write_report_csv(out_dir / "cardmarket-matching-report.csv", report_rows)

    if args.update_portfolio:
        updated_portfolio = update_portfolio_payload(portfolio, updated_cards, market_summary)
        save_json(portfolio_path, updated_portfolio)
        save_js(portfolio_path.with_suffix(".js"), "portfolioData", updated_portfolio)
    if args.update_wishlist:
        updated_wishlist = update_wishlist_payload(wishlist, updated_wishlist_items, wishlist_summary)
        save_json(wishlist_path, updated_wishlist)
        save_js(wishlist_path.with_suffix(".js"), "wishlistData", updated_wishlist)

    print("Resumen coleccion:")
    print(json.dumps(market_summary, ensure_ascii=False, indent=2))
    if wishlist_price_items:
        print("Resumen wishlist:")
        print(json.dumps(wishlist_summary, ensure_ascii=False, indent=2))
    print(f"Generado: {out_dir / 'market-prices.json'}")
    print(f"Reporte:  {out_dir / 'cardmarket-matching-report.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
