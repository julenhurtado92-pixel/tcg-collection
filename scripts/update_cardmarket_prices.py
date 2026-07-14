#!/usr/bin/env python3
"""
Actualiza precios de mercado usando Cardmarket Data Tables y, en modo V7,
scraping directo de las ofertas visibles de cada producto resuelto.

Pipeline V7:
1. Descarga Product Catalog y Price Guides publicos de Cardmarket.
2. Resuelve el idProduct por nombre/TCG/edicion/variante.
3. Abre la pagina publica del producto con filtros de idioma y condicion.
4. Extrae ofertas/listings visibles, filtra idioma, condicion NM+, Europa y no UK.
5. Calcula la media de las N ofertas validas mas baratas.
"""
from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import html as html_lib
import json
import math
import os
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.request
from urllib.parse import urlencode, quote, quote_plus, urljoin
from dataclasses import dataclass, field
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple, Set

try:
    from bs4 import BeautifulSoup  # type: ignore
except Exception:  # pragma: no cover - fallback sin dependencia opcional
    BeautifulSoup = None  # type: ignore

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


# V6 hibrida: Data Tables para resolver idProduct y un proveedor live para
# listings filtrables por idioma/condicion/pais. Por defecto se mantiene el
# modo Data Tables para que el pipeline antiguo siga funcionando sin claves.
DEFAULT_LIVE_API_BASE = "https://cardmarketapi.com/api/v1/card"
DEFAULT_LIVE_API_KEY_ENV = "CARDMARKET_LIVE_API_KEY"
LIVE_PRICE_SOURCE = "Cardmarket Live Listings"
HYBRID_PRICE_SOURCE = "Cardmarket Data Tables + Live Listings"
SCRAPE_PRICE_SOURCE = "Cardmarket Data Tables + Direct Scraping"
CARDMARKET_BASE_URL = "https://www.cardmarket.com"
DEFAULT_CARDMARKET_COOKIE_ENV = "CARDMARKET_COOKIE"
DEFAULT_SCRAPE_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0 Safari/537.36"
)
DEFAULT_SCRYFALL_USER_AGENT = "TCG-Collection-Price-Updater/1.1 (+personal collection; contact local user)"
SCRYFALL_API_BASE = "https://api.scryfall.com"
SCRYFALL_CARDMARKET_SOURCE = "Scryfall cardmarket_id + Cardmarket Data Tables"

CARDMARKET_LANGUAGE_IDS = {
    "english": "1",
    "french": "2",
    "german": "3",
    "spanish": "4",
    "italian": "5",
    "chinese-s": "6",
    "japanese": "7",
    "portuguese": "8",
    "russian": "9",
    "korean": "10",
    "chinese-t": "11",
    "dutch": "12",
    "polish": "13",
    "czech": "14",
    "hungarian": "15",
}

# Cardmarket usa minCondition con 1 como mejor estado y 7 como peor.
CARDMARKET_CONDITION_IDS = {
    "mt": "1",
    "nm": "2",
    "ex": "3",
    "gd": "4",
    "lp": "5",
    "pl": "6",
    "po": "7",
}

LANGUAGE_ALIASES = {
    "english": "english", "ingles": "english", "inglés": "english", "en": "english", "1": "english",
    "french": "french", "frances": "french", "francés": "french", "fr": "french", "2": "french",
    "german": "german", "aleman": "german", "alemán": "german", "de": "german", "3": "german",
    "spanish": "spanish", "espanol": "spanish", "español": "spanish", "castellano": "spanish", "es": "spanish", "4": "spanish",
    "italian": "italian", "italiano": "italian", "it": "italian", "5": "italian",
    "chinese s": "chinese-s", "chinese simplified": "chinese-s", "chino simplificado": "chinese-s", "6": "chinese-s",
    "japanese": "japanese", "japones": "japanese", "japonés": "japanese", "jp": "japanese", "ja": "japanese", "7": "japanese",
    "portuguese": "portuguese", "portugues": "portuguese", "portugués": "portuguese", "pt": "portuguese", "8": "portuguese",
    "russian": "russian", "ruso": "russian", "ru": "russian", "9": "russian",
    "korean": "korean", "coreano": "korean", "ko": "korean", "10": "korean",
    "chinese t": "chinese-t", "chinese traditional": "chinese-t", "chino tradicional": "chinese-t", "11": "chinese-t",
    "dutch": "dutch", "neerlandes": "dutch", "neerlandés": "dutch", "holandes": "dutch", "holandés": "dutch", "nl": "dutch", "12": "dutch",
    "polish": "polish", "polaco": "polish", "pl": "polish", "13": "polish",
    "czech": "czech", "checo": "czech", "cs": "czech", "cz": "czech", "14": "czech",
    "hungarian": "hungarian", "hungaro": "hungarian", "húngaro": "hungarian", "hu": "hungarian", "15": "hungarian",
}

CONDITION_RANK = {
    "po": 1, "poor": 1,
    "pl": 2, "played": 2,
    "lp": 3, "light played": 3, "lightly played": 3,
    "gd": 4, "good": 4,
    "ex": 5, "excellent": 5,
    "nm": 6, "near mint": 6, "nearmint": 6,
    "mt": 7, "mint": 7,
}
CONDITION_CANONICAL = {
    "poor": "po", "played": "pl", "light played": "lp", "lightly played": "lp",
    "good": "gd", "excellent": "ex", "near mint": "nm", "nearmint": "nm", "mint": "mt",
}

UK_COUNTRY_KEYS = {
    "gb", "uk", "gbr", "unitedkingdom", "greatbritain", "england", "scotland", "wales",
    "northernireland", "reino unido", "reinounido", "granbretana", "gran bretaña", "granbretana",
    "jersey", "guernsey", "isleofman",
}

EUROPE_COUNTRY_CODES = {
    "AL", "AD", "AT", "BY", "BE", "BA", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR",
    "DE", "GR", "HU", "IS", "IE", "IT", "XK", "LV", "LI", "LT", "LU", "MT", "MD", "MC",
    "ME", "NL", "MK", "NO", "PL", "PT", "RO", "SM", "RS", "SK", "SI", "ES", "SE", "CH",
    "UA", "VA",
}

EUROPE_COUNTRY_KEYS = {
    "albania", "andorra", "austria", "belarus", "belgica", "belgium", "bosnia", "bosniaherzegovina",
    "bulgaria", "croatia", "cyprus", "chipre", "czechia", "czechrepublic", "republicacheca", "denmark",
    "dinamarca", "estonia", "finland", "finlandia", "france", "francia", "germany", "alemania",
    "greece", "grecia", "hungary", "hungria", "iceland", "islandia", "ireland", "irlanda", "italy",
    "italia", "kosovo", "latvia", "letonia", "liechtenstein", "lithuania", "lituania", "luxembourg",
    "luxemburgo", "malta", "moldova", "monaco", "montenegro", "netherlands", "thenetherlands", "holanda",
    "paisesbajos", "northmacedonia", "macedonia", "norway", "noruega", "poland", "polonia", "portugal",
    "romania", "sanmarino", "serbia", "slovakia", "eslovaquia", "slovenia", "eslovenia", "spain",
    "espana", "españa", "sweden", "suecia", "switzerland", "suiza", "ukraine", "ucrania", "vatican",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def log(message: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {message}", flush=True)


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


@dataclass
class LiveListingsConfig:
    enabled: bool = False
    base_url: str = DEFAULT_LIVE_API_BASE
    api_key_env: str = DEFAULT_LIVE_API_KEY_ENV
    api_key: str = ""
    api_key_query_param: str = ""
    language: str = "auto"
    condition: str = "nm"
    sample_size: int = 5
    exclude_uk: bool = True
    require_europe: bool = True
    cache_dir: Path = field(default_factory=lambda: Path(".cache/cardmarket-live"))
    cache_hours: float = 1.0
    force: bool = False
    sleep: float = 0.35
    timeout_seconds: int = 35
    max_items: int = 0

    def resolved_api_key(self) -> str:
        return text(self.api_key or os.environ.get(self.api_key_env, ""))


@dataclass
class ScrapeListingsConfig:
    enabled: bool = False
    site_language: str = "en"
    language: str = "auto"
    condition: str = "nm"
    sample_size: int = 5
    exclude_uk: bool = True
    require_europe: bool = True
    require_language: bool = True
    require_condition: bool = True
    cache_dir: Path = field(default_factory=lambda: Path(".cache/cardmarket-scrape"))
    cache_hours: float = 2.0
    force: bool = False
    sleep: float = 1.2
    timeout_seconds: int = 45
    max_items: int = 0
    user_agent: str = DEFAULT_SCRAPE_USER_AGENT
    accept_language: str = "en-US,en;q=0.9,es;q=0.8"
    cookie_env: str = DEFAULT_CARDMARKET_COOKIE_ENV
    cookie: str = ""
    debug_html: bool = False
    search_fallback: bool = True
    max_search_candidates: int = 5
    fallback_to_priceguide: bool = True

    def resolved_cookie(self) -> str:
        return text(self.cookie or os.environ.get(self.cookie_env, ""))


@dataclass
class ScryfallCardmarketConfig:
    enabled: bool = True
    cache_dir: Path = field(default_factory=lambda: Path(".cache/scryfall-cardmarket"))
    cache_hours: float = 24 * 14
    force: bool = False
    sleep: float = 0.25
    timeout_seconds: int = 30
    user_agent: str = DEFAULT_SCRYFALL_USER_AGENT
    max_retries: int = 4


ScryfallResolverConfig = ScryfallCardmarketConfig


class ScrapeBlockedError(RuntimeError):
    pass


class ScrapeNoProductPageError(RuntimeError):
    pass


def language_slug(value: Any) -> Optional[str]:
    raw = text(value)
    if not raw:
        return None
    normalized = normalize(raw)
    compact = norm_key(raw)
    return LANGUAGE_ALIASES.get(normalized) or LANGUAGE_ALIASES.get(compact) or None


def resolve_listing_language(item: Dict[str, Any], configured_language: str) -> Optional[str]:
    configured = text(configured_language).lower()
    if configured and configured != "auto":
        return language_slug(configured) or configured
    return language_slug(item.get("language"))


def condition_slug(value: Any, default: str = "nm") -> str:
    raw = normalize(value)
    if not raw:
        return default
    compact = norm_key(raw)
    if raw in CONDITION_CANONICAL:
        return CONDITION_CANONICAL[raw]
    if compact in CONDITION_CANONICAL:
        return CONDITION_CANONICAL[compact]
    if raw in CONDITION_RANK:
        return raw
    if compact in CONDITION_RANK:
        return compact
    return default


def condition_rank(value: Any) -> Optional[int]:
    slug = condition_slug(value, default="")
    return CONDITION_RANK.get(slug) if slug else None


def condition_is_at_least(value: Any, minimum: str) -> bool:
    rank = condition_rank(value)
    min_rank = condition_rank(minimum) or CONDITION_RANK["nm"]
    return rank is not None and rank >= min_rank


def country_key(value: Any) -> str:
    return norm_key(value)


def listing_get(obj: Any, paths: Iterable[str]) -> Any:
    if not isinstance(obj, dict):
        return None
    lower = {norm_key(k): v for k, v in obj.items()}
    for path in paths:
        current: Any = obj
        ok = True
        for part in path.split("."):
            if not isinstance(current, dict):
                ok = False
                break
            if part in current:
                current = current[part]
            else:
                current_lower = {norm_key(k): v for k, v in current.items()}
                key = norm_key(part)
                if key not in current_lower:
                    ok = False
                    break
                current = current_lower[key]
        if ok and current not in (None, ""):
            return current
        key = norm_key(path)
        if key in lower and lower[key] not in (None, ""):
            return lower[key]
    return None


def extract_live_listings(payload: Any) -> List[Dict[str, Any]]:
    if isinstance(payload, list):
        return [entry for entry in payload if isinstance(entry, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ["listings", "offers", "articles", "sellers", "results", "items", "data"]:
        value = payload.get(key)
        if isinstance(value, list):
            return [entry for entry in value if isinstance(entry, dict)]
        if isinstance(value, dict):
            nested = extract_live_listings(value)
            if nested:
                return nested
    return []


def payload_fetched_at(payload: Any) -> str:
    if isinstance(payload, dict):
        for key in ["fetched_at", "fetchedAt", "updated_at", "updatedAt", "processedAt", "lastUpdated"]:
            value = text(payload.get(key))
            if value:
                return value
        data = payload.get("data")
        if isinstance(data, dict):
            return payload_fetched_at(data)
    return now_iso()


def listing_price(listing: Dict[str, Any]) -> Optional[float]:
    value = listing_get(listing, [
        "price", "price.value", "price.amount", "priceEUR", "price_eur", "amount", "value",
        "sellPrice", "from", "total", "totalPrice",
    ])
    return round_money(value)


def listing_language(listing: Dict[str, Any]) -> Optional[str]:
    value = listing_get(listing, ["lang", "language", "cardLanguage", "languageName", "product.language"])
    return language_slug(value)


def listing_condition(listing: Dict[str, Any]) -> Optional[str]:
    value = listing_get(listing, ["cond", "condition", "cardCondition", "grade", "product.condition"])
    if value in (None, ""):
        return None
    return condition_slug(value, default="") or None


def listing_country_value(listing: Dict[str, Any]) -> str:
    value = listing_get(listing, [
        "country", "countryCode", "sellerCountry", "sellerCountryCode", "seller.country",
        "seller.countryCode", "seller.location.country", "location.country",
    ])
    return text(value)


def is_uk_country(value: Any) -> bool:
    raw = text(value)
    if not raw:
        return False
    compact = country_key(raw)
    normalized = normalize(raw)
    return compact.upper() in {"GB", "UK", "GBR"} or compact in UK_COUNTRY_KEYS or normalized in UK_COUNTRY_KEYS


def is_europe_country(value: Any) -> bool:
    raw = text(value)
    if not raw:
        return False
    compact = country_key(raw)
    normalized = normalize(raw)
    if compact.upper() in EUROPE_COUNTRY_CODES:
        return True
    return compact in EUROPE_COUNTRY_KEYS or normalized in EUROPE_COUNTRY_KEYS


def listing_foil_flag(listing: Dict[str, Any]) -> Optional[bool]:
    value = listing_get(listing, [
        "foil", "isFoil", "is_foil", "reverseHolo", "isReverseHolo", "product.foil", "features.foil",
        "attributes.foil", "variant",
    ])
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    normalized = normalize(value)
    compact = norm_key(value)
    if normalized in {"true", "yes", "si", "foil", "holo", "reverse holo"} or compact in {"true", "yes", "si", "foil", "holo", "reverseholo"}:
        return True
    if "non foil" in normalized or compact in {"false", "no", "nonfoil", "regular", "normal"}:
        return False
    return None


def cardmarket_language_id(language: str) -> Optional[str]:
    slug = language_slug(language) or text(language).lower()
    return CARDMARKET_LANGUAGE_IDS.get(slug)


def cardmarket_condition_id(condition: str) -> str:
    return CARDMARKET_CONDITION_IDS.get(condition_slug(condition, default="nm"), CARDMARKET_CONDITION_IDS["nm"])


def cardmarket_slug_segment(value: Any) -> str:
    raw = strip_accents(text(value))
    raw = raw.replace("&", " and ")
    raw = re.sub(r"[’'`´]", "", raw)
    raw = re.sub(r"[^A-Za-z0-9]+", "-", raw)
    raw = re.sub(r"-+", "-", raw).strip("-")
    return quote(raw or "Product", safe="")


def cardmarket_category_path(product: Any) -> str:
    kind = text(product.product_kind if hasattr(product, "product_kind") else product.get("productKind"))
    category = normalize(product.category_name if hasattr(product, "category_name") else product.get("categoryName"))
    name = normalize(product.name if hasattr(product, "name") else product.get("name"))
    haystack = f"{category} {name}"
    if kind == "single" or "single" in category:
        return "Singles"
    if kind == "accessory" or "accessor" in haystack or "sleeve" in haystack or "deck box" in haystack or "playmat" in haystack:
        return "Accessories"
    if "booster box" in haystack or "display" in haystack:
        return "Booster-Boxes"
    if "booster" in haystack and "box" not in haystack:
        return "Boosters"
    if "set" in haystack or "lot" in haystack or "collection" in haystack:
        return "Sets-Lots-and-Collections"
    return "Sealed-Products"


def product_detail_url(product: Any, item: Optional[Dict[str, Any]] = None, *, site_language: str = "en") -> str:
    raw = product.raw if hasattr(product, "raw") else product
    id_product = text(product.id_product if hasattr(product, "id_product") else product.get("idProduct"))
    if isinstance(raw, dict):
        for key in ["scryfallCardmarketUrl", "url", "website", "webUrl", "cardmarketUrl", "productUrl"]:
            value = text(raw.get(key))
            if value:
                absolute = urljoin(CARDMARKET_BASE_URL, value)
                if id_product and "/Products/Search" not in absolute and "idProduct=" not in absolute:
                    absolute = append_query_params(absolute, {"idProduct": id_product})
                return absolute
    game_slug = product.game_slug if hasattr(product, "game_slug") else text(product.get("game", "magic"))
    game_path = GAMES.get(game_slug, {}).get("cardmarket_path", "Magic")
    category_path = cardmarket_category_path(product)
    name = product.name if hasattr(product, "name") else text(product.get("name"))
    expansion = text(product.expansion_name if hasattr(product, "expansion_name") else product.get("expansionName"))
    # Las Data Tables actuales a menudo traen idExpansion pero no expansionName.
    # Para scraping construimos una URL de producto con la edicion del item como fallback.
    if not expansion and item is not None:
        expansion = text(item.get("edition"))
    site = re.sub(r"[^a-z]", "", text(site_language).lower()) or "en"
    if category_path == "Accessories":
        url = f"{CARDMARKET_BASE_URL}/{site}/{game_path}/Products/Accessories/{cardmarket_slug_segment(name)}"
    elif expansion:
        url = (
            f"{CARDMARKET_BASE_URL}/{site}/{game_path}/Products/{category_path}/"
            f"{cardmarket_slug_segment(expansion)}/{cardmarket_slug_segment(name)}"
        )
    else:
        url = product_url(game_slug, product)
    if id_product and "/Products/Search" not in url and "idProduct=" not in url:
        url = append_query_params(url, {"idProduct": id_product})
    return url


def product_search_url(product: Any, item: Dict[str, Any], *, site_language: str = "en") -> str:
    game_slug = product.game_slug if hasattr(product, "game_slug") else game_slug_for_tcg(item.get("tcg"), item)
    game_path = GAMES.get(game_slug, {}).get("cardmarket_path", "Magic")
    site = re.sub(r"[^a-z]", "", text(site_language).lower()) or "en"
    query = text(product.name if hasattr(product, "name") else product.get("name") or item.get("cardName") or item.get("name"))
    return f"{CARDMARKET_BASE_URL}/{site}/{game_path}/Products/Search?searchString={quote_plus(query)}"


def append_query_params(url: str, params: Dict[str, str]) -> str:
    if not params:
        return url
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}{urlencode(params)}"


def scrape_filter_params(language: str, condition: str) -> Dict[str, str]:
    params: Dict[str, str] = {}
    language_id = cardmarket_language_id(language)
    if language_id:
        params["language"] = language_id
    params["minCondition"] = cardmarket_condition_id(condition)
    return params


def scrape_cache_path(config: ScrapeListingsConfig, url: str) -> Path:
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()
    return config.cache_dir / f"{digest}.html"


def read_text_file(path: Path, fallback: str = "") -> str:
    if not path.exists():
        return fallback
    return path.read_text(encoding="utf-8", errors="replace")


def write_text_file(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload, encoding="utf-8")


def html_looks_blocked(html: str, status: Optional[int] = None) -> bool:
    lowered = (html or "").lower()
    if status in {401, 403, 407, 429, 503}:
        return True
    block_markers = [
        "just a moment", "cf-chl", "cloudflare", "checking your browser",
        "captcha", "access denied", "unusual traffic", "blocked",
    ]
    return any(marker in lowered for marker in block_markers)


def html_is_product_page(html: str) -> bool:
    lowered = (html or "").lower()
    return "article-row" in lowered or "table-body" in lowered and "price-container" in lowered


def fetch_scrape_html(url: str, config: ScrapeListingsConfig, *, referer: str = "") -> Tuple[str, str]:
    cache_path = scrape_cache_path(config, url)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    if not config.force and cache_is_fresh(cache_path, config.cache_hours):
        return read_text_file(cache_path), url

    headers = {
        "User-Agent": text(config.user_agent or DEFAULT_SCRAPE_USER_AGENT),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": text(config.accept_language or "en-US,en;q=0.9"),
        "DNT": "1",
        "Upgrade-Insecure-Requests": "1",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none" if not referer else "same-origin",
        "Sec-Fetch-User": "?1",
    }
    cookie = config.resolved_cookie()
    if cookie:
        headers["Cookie"] = cookie
    if referer:
        headers["Referer"] = referer

    request = urllib.request.Request(url, headers=headers)
    last_error: Optional[BaseException] = None
    for attempt in range(1, 4):
        try:
            log(f"Scraping Cardmarket intento {attempt}/3: {url}")
            with urllib.request.urlopen(request, timeout=config.timeout_seconds) as response:
                raw = response.read()
                final_url = response.geturl() or url
                status = getattr(response, "status", None)
            html = raw.decode("utf-8", errors="replace")
            if html_looks_blocked(html, status):
                if config.debug_html:
                    write_text_file(cache_path.with_suffix(".blocked.html"), html)
                raise ScrapeBlockedError(f"respuesta bloqueada o challenge HTTP {status}")
            write_text_file(cache_path, html)
            if config.sleep:
                time.sleep(config.sleep)
            return html, final_url
        except urllib.error.HTTPError as exc:
            last_error = exc
            body = ""
            try:
                body = exc.read().decode("utf-8", errors="replace")
            except Exception:
                body = ""
            if html_looks_blocked(body, exc.code):
                if config.debug_html:
                    write_text_file(cache_path.with_suffix(".blocked.html"), body)
                raise ScrapeBlockedError(f"HTTP {exc.code}: posible bloqueo/challenge") from exc
            if exc.code == 429 and attempt < 3:
                retry_after = to_number(exc.headers.get("Retry-After")) or (5 * attempt)
                time.sleep(float(retry_after))
                continue
            break
        except ScrapeBlockedError:
            raise
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_error = exc
            if attempt < 3:
                time.sleep(2 * attempt)
                continue
            break
    raise RuntimeError(f"No se pudo descargar HTML Cardmarket: {last_error}")


def bs4_soup(html: str) -> Any:
    if BeautifulSoup is None:
        return None
    try:
        return BeautifulSoup(html, "html.parser")
    except Exception:
        return None


def bs4_first_text(node: Any, selectors: List[str]) -> Optional[str]:
    if node is None:
        return None
    for selector in selectors:
        found = node.select_one(selector)
        if found:
            value = found.get_text(" ", strip=True)
            if value:
                return value
    return None


def bs4_first_attr(node: Any, selectors: List[str], attrs: List[str]) -> Optional[str]:
    if node is None:
        return None
    for selector in selectors:
        found = node.select_one(selector)
        if not found:
            continue
        for attr in attrs:
            value = found.get(attr)
            if value:
                return text(value)
    return None


def bs4_attr_values(node: Any, selectors: List[str], attrs: List[str]) -> List[str]:
    if node is None:
        return []
    values: List[str] = []
    for selector in selectors:
        for found in node.select(selector):
            for attr in attrs:
                value = found.get(attr)
                if value:
                    values.append(text(value))
    return values


def parse_quantity(value: Any) -> Optional[int]:
    number = to_number(value)
    if number is None:
        return None
    return int(number) if float(number).is_integer() else None


def scrape_row_condition(row: Any) -> Optional[str]:
    raw = bs4_first_text(row, [
        ".article-condition span", "a.article-condition span", ".product-attributes .badge",
        ".product-attributes a span", "span.badge",
    ])
    if raw:
        slug = condition_slug(raw, default="")
        return slug.upper() if slug else None
    return None


def scrape_row_language(row: Any) -> Optional[str]:
    raw = bs4_first_attr(row, [
        ".product-attributes span.icon[aria-label]",
        ".product-attributes span.icon[data-bs-original-title]",
        ".product-attributes span.icon[data-original-title]",
        ".product-attributes span.icon[title]",
        "span.icon[data-original-title]",
    ], ["aria-label", "data-bs-original-title", "data-original-title", "title"])
    slug = language_slug(raw)
    return slug or raw


def scrape_row_country(row: Any) -> Optional[str]:
    selectors = [
        ".seller-info span.icon[aria-label]",
        ".seller-info span.icon[data-bs-original-title]",
        ".seller-info span.icon[data-original-title]",
        ".seller-info span.icon[title]",
        ".col-seller span.icon[aria-label]",
        ".col-seller span.icon[data-bs-original-title]",
        ".col-seller span.icon[data-original-title]",
        ".col-seller span.icon[title]",
        ".seller-name span.icon[aria-label]",
        ".seller-name span.icon[data-bs-original-title]",
        ".seller-name span.icon[data-original-title]",
        ".seller-name span.icon[title]",
    ]
    values = bs4_attr_values(row, selectors, ["aria-label", "data-bs-original-title", "data-original-title", "title"])
    for value in values:
        if language_slug(value) or condition_rank(value):
            continue
        if is_europe_country(value) or is_uk_country(value):
            return value
    return values[0] if values else None


def scrape_row_flags(row: Any) -> Dict[str, bool]:
    values = bs4_attr_values(row, [
        ".product-attributes span.icon", ".product-attributes span[data-bs-original-title]",
        ".product-attributes span[data-original-title]", ".product-attributes span[title]",
    ], ["aria-label", "data-bs-original-title", "data-original-title", "title"])
    joined = normalize(" ".join(values))
    return {
        "isFoil": "foil" in joined or "holo" in joined,
        "isReverseHolo": "reverse" in joined and "holo" in joined,
        "isSigned": "signed" in joined or "firma" in joined,
        "isAltered": "altered" in joined or "alterad" in joined,
    }


def parse_cardmarket_offers_with_bs4(html: str, product_url_value: str, limit: int = 350) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    soup = bs4_soup(html)
    if soup is None:
        return {}, []
    meta = {
        "productUrl": product_url_value,
        "cardName": bs4_first_text(soup, ["h1", ".page-title-container h1"]),
        "expansion": bs4_first_text(soup, ["a[href*='/Expansions/']", ".expansion-name"]),
    }
    rows = soup.select(".article-row") or soup.select("[id^='articleRow']")
    offers: List[Dict[str, Any]] = []
    for row in rows:
        price_raw = bs4_first_text(row, [
            ".price-container .color-primary", ".price-container span.text-nowrap",
            ".col-offer .price-container", ".price-container",
        ])
        amount_raw = bs4_first_text(row, [
            ".amount-container .item-count", ".col-offer .amount-container", ".amount-container",
            ".actions-container input[name='amount']",
        ])
        seller_name = bs4_first_text(row, [".seller-name a", ".col-seller a", "span.seller-name a", ".seller-info a"])
        seller_score = bs4_first_attr(row, [
            ".seller-extended", ".seller-info .icon[aria-label]", ".seller-info .icon[data-bs-original-title]",
        ], ["title", "aria-label", "data-bs-original-title", "data-original-title"])
        flags = scrape_row_flags(row)
        offer = {
            "sellerName": seller_name,
            "sellerRating": seller_score,
            "sellerCountry": scrape_row_country(row),
            "country": scrape_row_country(row),
            "price": round_money(price_raw),
            "priceRaw": price_raw,
            "currency": "EUR",
            "condition": scrape_row_condition(row),
            "language": scrape_row_language(row),
            "quantity": parse_quantity(amount_raw),
            "sourceUrl": product_url_value,
            **flags,
        }
        offers.append(offer)
        if len(offers) >= limit:
            break
    return meta, offers


def parse_cardmarket_offers_fallback(html: str, product_url_value: str, limit: int = 350) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    # Fallback muy defensivo sin bs4: extrae bloques article-row y busca precios/condiciones.
    rows = re.split(r"""<[^>]+class=["'][^"']*article-row[^"']*["'][^>]*>""", html, flags=re.I)
    offers: List[Dict[str, Any]] = []
    for row_html in rows[1:]:
        row_html = row_html[: row_html.find('</div>') if '</div>' in row_html else len(row_html)]
        text_row = html_lib.unescape(re.sub(r"<[^>]+>", " ", row_html))
        prices = re.findall(r"\d[\d.]*,\d{2}\s*€", text_row)
        price = round_money(prices[0]) if prices else None
        cond_match = re.search(r"\b(MT|NM|EX|GD|LP|PL|PO)\b", text_row, flags=re.I)
        offer = {
            "price": price,
            "priceRaw": prices[0] if prices else None,
            "currency": "EUR",
            "condition": cond_match.group(1).upper() if cond_match else None,
            "language": None,
            "sellerCountry": None,
            "country": None,
            "sourceUrl": product_url_value,
        }
        offers.append(offer)
        if len(offers) >= limit:
            break
    return {"productUrl": product_url_value}, offers


def parse_cardmarket_offers(html: str, product_url_value: str, limit: int = 350) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    meta, offers = parse_cardmarket_offers_with_bs4(html, product_url_value, limit=limit)
    if offers:
        return meta, offers
    return parse_cardmarket_offers_fallback(html, product_url_value, limit=limit)


def extract_product_links_from_search(html: str, base_url: str) -> List[Tuple[str, str]]:
    links: List[Tuple[str, str]] = []
    seen: Set[str] = set()
    soup = bs4_soup(html)
    if soup is not None:
        for anchor in soup.select("a[href*='/Products/']"):
            href = text(anchor.get("href"))
            if not href or "/Products/Search" in href or "/Images/" in href:
                continue
            absolute = urljoin(base_url, href.split("?")[0])
            if absolute in seen:
                continue
            seen.add(absolute)
            links.append((absolute, anchor.get_text(" ", strip=True)))
        return links
    for match in re.finditer(r"""href=["']([^"']*/Products/[^"']+)["']""", html or "", flags=re.I):
        href = match.group(1)
        if "/Products/Search" in href or "/Images/" in href:
            continue
        absolute = urljoin(base_url, href.split("?")[0])
        if absolute not in seen:
            seen.add(absolute)
            links.append((absolute, ""))
    return links


def score_product_link(url: str, label: str, product: Any, item: Dict[str, Any]) -> float:
    name = text(product.name if hasattr(product, "name") else product.get("name") or item.get("cardName") or item.get("name"))
    expansion = text(product.expansion_name if hasattr(product, "expansion_name") else product.get("expansionName") or item.get("edition"))
    haystack = normalize(f"{url} {label}")
    score = 0.0
    name_norm = normalize(name)
    exp_norm = normalize(expansion)
    if name_norm and name_norm in haystack:
        score += 10
    else:
        score += name_similarity(name, label or url) * 7
    if exp_norm and exp_norm in haystack:
        score += 6
    if "/Products/Singles/" in url and not is_sealed_item(item):
        score += 2
    if "/Products/Accessories/" in url and is_sealed_item(item):
        score += 1
    return score


def resolve_scrape_product_html(
    item: Dict[str, Any],
    product: Any,
    *,
    language: str,
    condition: str,
    config: ScrapeListingsConfig,
) -> Tuple[str, str, Dict[str, Any]]:
    params = scrape_filter_params(language, condition)
    direct_url = product_detail_url(product, item=item, site_language=config.site_language)
    attempts: List[Tuple[str, str]] = [("direct", direct_url)]
    if direct_url and "/Products/Search" not in direct_url:
        attempts.append(("direct_unfiltered", direct_url.split("?")[0]))
    tried: List[str] = []
    errors: List[str] = []

    for source, base_url in attempts:
        url = append_query_params(base_url, params) if "/Products/Search" not in base_url else base_url
        if url in tried:
            continue
        tried.append(url)
        try:
            html, final_url = fetch_scrape_html(url, config)
        except ScrapeBlockedError:
            raise
        except Exception as exc:  # noqa: BLE001 - se intenta fallback por busqueda.
            errors.append(f"{source}:{type(exc).__name__}:{str(exc)[:120]}")
            continue
        if html_is_product_page(html):
            return html, final_url, {"urlSource": source, "attempted": tried, "errors": errors}

    if not config.search_fallback:
        raise ScrapeNoProductPageError(f"no_es_pagina_producto:{direct_url}; errores={' | '.join(errors)}")

    search_url = product_search_url(product, item, site_language=config.site_language)
    try:
        search_html, final_search_url = fetch_scrape_html(search_url, config)
    except ScrapeBlockedError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise ScrapeNoProductPageError(f"busqueda_fallida:{type(exc).__name__}:{str(exc)[:160]}; errores={' | '.join(errors)}") from exc
    if html_is_product_page(search_html):
        return search_html, final_search_url, {"urlSource": "search_redirect", "attempted": tried + [search_url], "errors": errors}

    links = extract_product_links_from_search(search_html, CARDMARKET_BASE_URL)
    ranked = sorted(
        ((score_product_link(url, label, product, item), url, label) for url, label in links),
        key=lambda row: row[0],
        reverse=True,
    )
    for score, candidate_url, label in ranked[: max(int(config.max_search_candidates or 5), 1)]:
        candidate_filtered = append_query_params(candidate_url, params)
        if candidate_filtered in tried:
            continue
        tried.append(candidate_filtered)
        try:
            html, final_url = fetch_scrape_html(candidate_filtered, config, referer=final_search_url)
        except ScrapeBlockedError:
            raise
        except Exception as exc:  # noqa: BLE001
            errors.append(f"candidate:{type(exc).__name__}:{str(exc)[:120]}")
            continue
        if html_is_product_page(html):
            return html, final_url, {
                "urlSource": "search_candidate",
                "searchUrl": final_search_url,
                "candidateLabel": label,
                "candidateScore": round(score, 2),
                "attempted": tried,
                "errors": errors,
            }

    raise ScrapeNoProductPageError(f"sin_pagina_producto; intentos={len(tried)}; candidatos={len(links)}; errores={' | '.join(errors)}")


def download_scraped_listing_payload(
    item: Dict[str, Any],
    product: Any,
    *,
    language: str,
    condition: str,
    config: ScrapeListingsConfig,
) -> Dict[str, Any]:
    html, final_url, details = resolve_scrape_product_html(item, product, language=language, condition=condition, config=config)
    meta, offers = parse_cardmarket_offers(html, final_url, limit=350)
    return {
        "fetchedAt": now_iso(),
        "productUrl": final_url,
        "listings": offers,
        "meta": meta,
        "details": details,
        "rawCount": len(offers),
    }


def filter_live_listings(
    listings: List[Dict[str, Any]],
    item: Dict[str, Any],
    *,
    language: str,
    condition: str,
    config: Any,
) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    reject_counts: Dict[str, int] = {}

    def reject(reason: str) -> None:
        reject_counts[reason] = reject_counts.get(reason, 0) + 1

    valid: List[Dict[str, Any]] = []
    wants_foil = is_foil(item.get("variant"))
    sealed = is_sealed_item(item)
    for listing in listings:
        price = listing_price(listing)
        if price is None:
            reject("sin_precio")
            continue

        lang = listing_language(listing)
        require_language = bool(getattr(config, "require_language", False))
        if language and not lang and require_language:
            reject("idioma_desconocido")
            continue
        if lang and language and lang != language:
            reject("idioma")
            continue

        cond = listing_condition(listing)
        require_condition = bool(getattr(config, "require_condition", False))
        if not cond and require_condition:
            reject("condicion_desconocida")
            continue
        if cond and not condition_is_at_least(cond, condition):
            reject("condicion")
            continue

        foil_flag = listing_foil_flag(listing)
        if not sealed:
            if wants_foil and foil_flag is not True:
                reject("variante_foil_no_confirmada")
                continue
            if not wants_foil and foil_flag is True:
                reject("variante_foil")
                continue

        country = listing_country_value(listing)
        if config.exclude_uk and is_uk_country(country):
            reject("uk")
            continue
        if config.require_europe and country and not is_europe_country(country):
            reject("fuera_europa")
            continue
        if config.require_europe and not country:
            reject("pais_desconocido")
            continue

        normalized = {
            "price": price,
            "language": lang or language,
            "condition": (cond or condition).upper(),
            "country": country,
        }
        quantity = to_number(listing_get(listing, ["quantity", "qty", "count", "available"]))
        if quantity is not None:
            normalized["quantity"] = int(quantity) if float(quantity).is_integer() else quantity
        valid.append(normalized)

    valid.sort(key=lambda row: row["price"])
    return valid, reject_counts


def build_live_url(config: LiveListingsConfig, product_id: int, params: Dict[str, str]) -> str:
    base = text(config.base_url or DEFAULT_LIVE_API_BASE)
    if "{id}" in base:
        url = base.replace("{id}", str(product_id))
    else:
        url = f"{base.rstrip('/')}/{product_id}"
    if params:
        separator = "&" if "?" in url else "?"
        url = f"{url}{separator}{urlencode(params)}"
    return url


def live_cache_path(config: LiveListingsConfig, product_id: int, language: str, condition: str) -> Path:
    safe = norm_key(f"{product_id}_{language}_{condition}")
    return config.cache_dir / f"{safe}.json"


def cache_is_fresh(path: Path, hours: float) -> bool:
    if not path.exists() or hours <= 0:
        return False
    max_age = hours * 3600
    return (time.time() - path.stat().st_mtime) <= max_age


def download_live_listing_payload(
    product_id: int,
    *,
    language: str,
    condition: str,
    config: LiveListingsConfig,
) -> Dict[str, Any]:
    api_key = config.resolved_api_key()
    if not api_key:
        raise RuntimeError(f"Falta la clave del proveedor live. Define el secreto/env {config.api_key_env} o usa --pricing-mode datatables.")

    params = {"language": language, "condition": condition}
    if config.api_key_query_param:
        params[config.api_key_query_param] = api_key
    url = build_live_url(config, product_id, params)
    cache_path = live_cache_path(config, product_id, language, condition)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    if not config.force and cache_is_fresh(cache_path, config.cache_hours):
        return load_json(cache_path, {})

    headers = {
        "User-Agent": "TCG-Collection-Price-Updater/1.1 (+local personal collection)",
        "Accept": "application/json,text/json,*/*",
    }
    if not config.api_key_query_param:
        headers["X-API-Key"] = api_key
    request = urllib.request.Request(url, headers=headers)

    last_error: Optional[BaseException] = None
    for attempt in range(1, 4):
        try:
            log(f"Listings live {product_id} ({language}/{condition}) intento {attempt}/3")
            with urllib.request.urlopen(request, timeout=config.timeout_seconds) as response:
                raw_bytes = response.read()
            payload = json.loads(raw_bytes.decode("utf-8-sig"))
            save_json(cache_path, payload)
            if config.sleep:
                time.sleep(config.sleep)
            return payload
        except urllib.error.HTTPError as exc:
            last_error = exc
            if exc.code == 429 and attempt < 3:
                retry_after = to_number(exc.headers.get("Retry-After")) or (2 * attempt)
                log(f"Rate limit live; esperando {retry_after}s")
                time.sleep(float(retry_after))
                continue
            break
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
            last_error = exc
            if attempt < 3:
                time.sleep(2 * attempt)
                continue
            break
    raise RuntimeError(f"No se pudieron descargar listings live para idProduct={product_id}: {last_error}")


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


def download_json(
    url: str,
    cache_path: Path,
    *,
    force: bool = False,
    sleep: float = 0.2,
    timeout_seconds: int = 35,
    retries: int = 2,
) -> Any:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    if cache_path.exists() and not force:
        log(f"Usando cache: {cache_path}")
        return load_json(cache_path, {})

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "TCG-Collection-Price-Updater/1.0 (+local personal collection)",
            "Accept": "application/json,text/json,*/*",
        },
    )

    last_error = None
    for attempt in range(1, retries + 2):
        log(f"Descargando ({attempt}/{retries + 1}): {url}")
        try:
            started = time.time()
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                raw_bytes = response.read()
                status = getattr(response, "status", "?")
            elapsed = time.time() - started
            log(f"OK {status}: {len(raw_bytes):,} bytes en {elapsed:.1f}s")
            raw = raw_bytes.decode("utf-8-sig")
            payload = json.loads(raw)
            save_json(cache_path, payload)
            if sleep:
                time.sleep(sleep)
            return payload
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError, OSError) as exc:
            last_error = exc
            log(f"ERROR descargando {url}: {type(exc).__name__}: {exc}")
            if attempt <= retries:
                time.sleep(2 * attempt)

    raise RuntimeError(f"No se pudo descargar {url} tras {retries + 1} intentos. Ultimo error: {last_error}")




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
    raw = product.raw if hasattr(product, "raw") else product
    if isinstance(raw, dict):
        for key in ["scryfallCardmarketUrl", "cardmarketUrl", "productUrl", "webUrl", "website", "url"]:
            value = text(raw.get(key))
            if value and "/Products/Search" not in value:
                return urljoin(CARDMARKET_BASE_URL, value)
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
        self.name_index: Dict[str, Dict[str, List[CatalogProduct]]] = {slug: {} for slug in GAMES}
        self.token_index: Dict[str, Dict[str, List[CatalogProduct]]] = {slug: {} for slug in GAMES}

    def build_indexes(self) -> None:
        self.name_index = {slug: {} for slug in GAMES}
        self.token_index = {slug: {} for slug in GAMES}
        for slug, products in self.products_by_game.items():
            for product in products:
                name_key = norm_key(product.name)
                if name_key:
                    self.name_index.setdefault(slug, {}).setdefault(name_key, []).append(product)
                text_for_tokens = f"{product.name} {product.expansion_name} {product.category_name}"
                for token in tokens(text_for_tokens):
                    if len(token) >= 3:
                        self.token_index.setdefault(slug, {}).setdefault(token, []).append(product)

    def search_candidates(self, item: Dict[str, Any], slug: str, *, limit: int = 900) -> List[CatalogProduct]:
        item_name = text(item.get("cardName") or item.get("name"))
        item_edition = text(item.get("edition"))
        exact_key = norm_key(item_name)
        candidates: Dict[int, CatalogProduct] = {}

        for product in self.name_index.get(slug, {}).get(exact_key, []):
            candidates[product.id_product] = product

        query_tokens = [tok for tok in tokens(f"{item_name} {item_edition}") if len(tok) >= 3]
        for tok in query_tokens:
            for product in self.token_index.get(slug, {}).get(tok, []):
                candidates[product.id_product] = product

        if not candidates:
            return []

        # Prefiltro barato: evita calcular SequenceMatcher contra cientos de miles de productos.
        item_name_tokens = tokens(item_name)
        item_full_tokens = tokens(f"{item_name} {item_edition}")
        ranked: List[Tuple[float, CatalogProduct]] = []
        sealed = is_sealed_item(item)
        for product in candidates.values():
            prod_name_tokens = tokens(product.name)
            prod_full_tokens = tokens(f"{product.name} {product.expansion_name} {product.category_name}")
            name_overlap = len(item_name_tokens & prod_name_tokens) / max(len(item_name_tokens), 1)
            full_overlap = len(item_full_tokens & prod_full_tokens) / max(len(item_full_tokens), 1)
            exact_bonus = 2.0 if norm_key(product.name) == exact_key else 0.0
            kind_bonus = 0.35 if ((sealed and product.product_kind in {"nonsingle", "accessory"}) or (not sealed and product.product_kind == "single")) else 0.0
            price_bonus = 0.2 if product.price else 0.0
            ranked.append((name_overlap * 3.0 + full_overlap + exact_bonus + kind_bonus + price_bonus, product))
        ranked.sort(key=lambda row: row[0], reverse=True)
        return [product for _, product in ranked[:limit]]

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
    catalog.build_indexes()
    log("Indices de búsqueda construidos")
    return catalog




def nested_get(data: Dict[str, Any], *keys: str) -> Any:
    current: Any = data
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def item_scryfall_set_code(item: Dict[str, Any]) -> str:
    candidates = [
        item.get("setCode"),
        nested_get(item, "scryfall", "set"),
        nested_get(item, "scryfall", "setCode"),
        nested_get(item, "imageResolution", "setCode"),
        nested_get(item, "imageResolution", "extraSearch", "setCode"),
    ]
    for value in candidates:
        normalized = re.sub(r"[^a-z0-9]", "", text(value).lower())
        if normalized:
            return normalized

    haystack = " ".join([
        text(nested_get(item, "imageResolution", "imageEndpoint")),
        text(nested_get(item, "imageResolution", "searchUri")),
        text(nested_get(item, "imageResolution", "scryfallUri")),
        text(nested_get(item, "images", "normal")),
        text(nested_get(item, "images", "small")),
    ])
    decoded = html_lib.unescape(haystack)
    decoded = decoded.replace("%3A", ":").replace("%3a", ":")
    patterns = [
        r"[?&]set=([a-z0-9]{2,8})",
        r"\be:([a-z0-9]{2,8})",
        r"/card/([a-z0-9]{2,8})/",
    ]
    for pattern in patterns:
        match = re.search(pattern, decoded, flags=re.I)
        if match:
            return re.sub(r"[^a-z0-9]", "", match.group(1).lower())
    return ""


def item_scryfall_id(item: Dict[str, Any]) -> str:
    return text(
        item.get("scryfallId")
        or nested_get(item, "scryfall", "id")
        or nested_get(item, "imageResolution", "scryfallId")
    )


def item_collector_number(item: Dict[str, Any]) -> str:
    return norm_key(
        item.get("collectorNumber")
        or nested_get(item, "scryfall", "collectorNumber")
        or nested_get(item, "imageResolution", "collectorNumber")
    )


def should_use_scryfall_resolver(item: Dict[str, Any]) -> bool:
    return game_slug_for_tcg(item.get("tcg"), item) == "magic" and not is_sealed_item(item)


def scryfall_cache_path(config: ScryfallResolverConfig, url: str) -> Path:
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()
    return config.cache_dir / f"{digest}.json"


def retry_after_seconds(headers: Any, fallback: float) -> float:
    raw = text(headers.get("Retry-After") if hasattr(headers, "get") else "")
    if raw:
        try:
            return max(0.0, min(120.0, float(raw)))
        except ValueError:
            pass
    return max(0.0, min(120.0, fallback))


def fetch_scryfall_json(url: str, config: ScryfallResolverConfig) -> Dict[str, Any]:
    cache_path = scryfall_cache_path(config, url)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    if not config.force and cache_is_fresh(cache_path, config.cache_hours):
        return load_json(cache_path, {})

    max_attempts = max(1, int(getattr(config, "max_retries", 4)) + 1)
    for attempt in range(1, max_attempts + 1):
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": text(config.user_agent or DEFAULT_SCRYFALL_USER_AGENT),
                "Accept": "application/json;q=0.9,*/*;q=0.1",
            },
        )
        try:
            suffix = f" intento {attempt}/{max_attempts}" if attempt > 1 else ""
            log(f"Resolviendo Cardmarket ID via Scryfall{suffix}: {url}")
            with urllib.request.urlopen(request, timeout=config.timeout_seconds) as response:
                raw = response.read().decode("utf-8", errors="replace")
            payload = json.loads(raw)
            save_json(cache_path, payload)
            if config.sleep:
                time.sleep(config.sleep)
            return payload if isinstance(payload, dict) else {}
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                save_json(cache_path, {"object": "error", "code": "not_found"})
                return {}

            retryable = exc.code == 429 or 500 <= exc.code < 600
            if retryable and attempt < max_attempts:
                fallback_wait = max(float(getattr(config, "sleep", 0.25) or 0.25), min(30.0, 2.0 ** attempt))
                wait_seconds = retry_after_seconds(getattr(exc, "headers", None), fallback_wait)
                log(f"Aviso: Scryfall HTTP {exc.code}; esperando {wait_seconds:.1f}s antes de reintentar")
                time.sleep(wait_seconds)
                continue

            if exc.code == 429:
                config.enabled = False
                log("Aviso: Scryfall ha devuelto 429 demasiadas veces; se desactiva el resolver Scryfall para el resto de esta ejecucion y se continua con Data Tables")
                return {}

            log(f"Aviso: Scryfall HTTP {exc.code}; se continua con Data Tables para este item")
            return {}
        except Exception as exc:  # noqa: BLE001 - el resolver Scryfall es auxiliar.
            log(f"Aviso: Scryfall resolver no disponible: {type(exc).__name__}: {str(exc)[:120]}")
            return {}

    return {}


def scryfall_query_url_for_item(item: Dict[str, Any]) -> str:
    scryfall_id = item_scryfall_id(item)
    if scryfall_id:
        return f"{SCRYFALL_API_BASE}/cards/{quote(scryfall_id)}"
    name = text(item.get("scryfallName") or item.get("cardName") or item.get("name"))
    escaped_name = name.replace('"', '\\"')
    query = f'!"{escaped_name}"'
    set_code = item_scryfall_set_code(item)
    if set_code:
        query += f" e:{set_code}"
    return f"{SCRYFALL_API_BASE}/cards/search?{urlencode({'unique': 'prints', 'order': 'set', 'q': query})}"


def scryfall_cards_from_payload(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    if payload.get("object") == "card":
        return [payload]
    data = payload.get("data")
    return [row for row in data if isinstance(row, dict)] if isinstance(data, list) else []


def scryfall_cardmarket_id(card: Dict[str, Any]) -> Optional[int]:
    raw_id = card.get("cardmarket_id") or card.get("cardmarketId")
    try:
        return int(raw_id)
    except (TypeError, ValueError):
        return None


def score_scryfall_card_for_item(card: Dict[str, Any], item: Dict[str, Any]) -> float:
    score = 0.0
    wanted_set = item_scryfall_set_code(item)
    card_set = norm_key(card.get("set"))
    if wanted_set and card_set == wanted_set:
        score += 50
    wanted_collector = item_collector_number(item)
    card_collector = norm_key(card.get("collector_number"))
    if wanted_collector and card_collector == wanted_collector:
        score += 100
    name = text(item.get("scryfallName") or item.get("cardName") or item.get("name"))
    card_name = text(card.get("name"))
    score += name_similarity(name, card_name) * 30
    finishes = {normalize(value) for value in (card.get("finishes") or []) if value}
    if is_foil(item.get("variant")):
        score += 8 if "foil" in finishes or "etched" in finishes else -4
    else:
        score += 8 if "nonfoil" in finishes else 0
    if scryfall_cardmarket_id(card):
        score += 12
    if card.get("purchase_uris", {}).get("cardmarket"):
        score += 6
    return score


def resolve_scryfall_cardmarket_product(
    item: Dict[str, Any],
    catalog: CardmarketCatalog,
    config: Optional[ScryfallResolverConfig],
) -> Tuple[Optional[CatalogProduct], Dict[str, Any]]:
    info: Dict[str, Any] = {"enabled": bool(config and config.enabled), "method": "scryfall_cardmarket_id"}
    if not config or not config.enabled or not should_use_scryfall_resolver(item):
        info["status"] = "skipped"
        return None, info

    url = scryfall_query_url_for_item(item)
    payload = fetch_scryfall_json(url, config)
    cards = scryfall_cards_from_payload(payload)
    info.update({
        "queryUrl": url,
        "setCode": item_scryfall_set_code(item),
        "collectorNumber": item_collector_number(item),
        "candidateCount": len(cards),
    })
    if not cards:
        info["status"] = "not_found"
        return None, info

    ranked = sorted(
        ((score_scryfall_card_for_item(card, item), card) for card in cards if scryfall_cardmarket_id(card)),
        key=lambda row: row[0],
        reverse=True,
    )
    if not ranked:
        info["status"] = "without_cardmarket_id"
        return None, info

    best_score, best_card = ranked[0]
    id_product = scryfall_cardmarket_id(best_card)
    product = catalog.products_by_id.get(int(id_product)) if id_product is not None else None
    if not product:
        info.update({"status": "id_not_in_datatables", "idProduct": id_product, "score": round(best_score, 2)})
        return None, info

    purchase_uris = best_card.get("purchase_uris") if isinstance(best_card.get("purchase_uris"), dict) else {}
    cardmarket_url = text((purchase_uris or {}).get("cardmarket"))
    if cardmarket_url:
        product.raw["scryfallCardmarketUrl"] = cardmarket_url
    product.raw["scryfallResolver"] = {
        "id": best_card.get("id"),
        "set": best_card.get("set"),
        "setName": best_card.get("set_name"),
        "collectorNumber": best_card.get("collector_number"),
        "cardmarketId": id_product,
        "score": round(best_score, 2),
    }
    if not product.expansion_name:
        product.expansion_name = text(best_card.get("set_name") or item.get("edition"))
    if not product.category_name:
        product.category_name = "Magic Single"
    if not product.product_kind:
        product.product_kind = "single"
    if not product.price:
        product.price = catalog.price_by_id.get(product.id_product, {})

    info.update({
        "status": "resolved",
        "idProduct": id_product,
        "score": round(best_score, 2),
        "scryfallId": best_card.get("id"),
        "scryfallSet": best_card.get("set"),
        "scryfallSetName": best_card.get("set_name"),
        "scryfallCollectorNumber": best_card.get("collector_number"),
        "cardmarketUrl": cardmarket_url,
    })
    return product, info

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


def product_name_base(name: str) -> str:
    # Muchos proveedores añaden códigos o descriptores entre paréntesis; para el
    # match estricto comparamos también una versión sin esos sufijos.
    return normalize(re.sub(r"\([^)]*\)", " ", name))


def strict_match_check(item: Dict[str, Any], product: CatalogProduct) -> Tuple[bool, str]:
    item_name = text(item.get("cardName") or item.get("name"))
    item_edition = text(item.get("edition"))
    name_norm = normalize(item_name)
    product_norm = normalize(product.name)
    product_base = product_name_base(product.name)
    name_sim = name_similarity(item_name, product.name)

    if name_norm and name_norm not in {product_norm, product_base} and name_sim < 0.94:
        return False, f"nombre_no_estricto:{round(name_sim * 100)}"

    if item_edition:
        ed_sim = edition_similarity(item_edition, product)
        expansion_signal = normalize(item_edition) in normalize(f"{product.expansion_name} {product.name} {product.category_name}")
        if ed_sim is not None and ed_sim < 0.86 and not expansion_signal:
            return False, f"edicion_no_estricta:{round(ed_sim * 100)}"
        if ed_sim is None and not expansion_signal:
            return False, "edicion_no_confirmada"

    # La variante se aplica de verdad en el filtro de listings. Aqui solo evitamos
    # resolver foils contra un producto que el price guide identifica claramente
    # como sin precio foil cuando no hay señal adicional posterior.
    if is_foil(item.get("variant")) and product.price:
        values, fallback = price_values(product.price, item.get("variant"))
        if fallback == "foil_to_normal" and not any(value is not None for value in values.values()):
            return False, "variante_foil_no_confirmada"

    return True, "match_estricto"


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


def priceguide_snapshot(market: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "source": "Cardmarket Data Tables",
        "unit": market.get("unit"),
        "selected": market.get("selected"),
        "selectedLabel": market.get("selectedLabel"),
        "sell": market.get("sell"),
        "low": market.get("low"),
        "trend": market.get("trend"),
        "avg": market.get("avg"),
        "avg1": market.get("avg1"),
        "avg7": market.get("avg7"),
        "avg30": market.get("avg30"),
    }


def live_filter_payload(language: str, condition: str, config: Any) -> Dict[str, Any]:
    return {
        "language": language,
        "condition": condition,
        "conditionMeaning": "esta condicion o superior",
        "sampleSize": config.sample_size,
        "region": "Europe" if config.require_europe else "any",
        "excludeUK": bool(config.exclude_uk),
    }


def live_problem_market_payload(
    market: Dict[str, Any],
    *,
    status: str,
    reason: str,
    language: str,
    condition: str,
    config: LiveListingsConfig,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    updated = dict(market)
    updated.update({
        "status": status,
        "source": HYBRID_PRICE_SOURCE,
        "pricingMode": "hybrid",
        "unit": None,
        "selected": None,
        "selectedLabel": None,
        "matchReason": reason,
        "lastUpdated": now_iso(),
        "fallbackPriceGuide": priceguide_snapshot(market),
        "listingFilter": live_filter_payload(language, condition, config),
        "liveListings": {
            "status": status,
            "reason": reason,
            "filter": live_filter_payload(language, condition, config),
            "validCount": 0,
            "sample": [],
        },
    })
    if extra:
        updated["liveListings"].update(extra)
    return updated


def build_live_market_payload(
    item: Dict[str, Any],
    market: Dict[str, Any],
    payload: Dict[str, Any],
    *,
    language: str,
    condition: str,
    config: LiveListingsConfig,
) -> Dict[str, Any]:
    raw_listings = extract_live_listings(payload)
    valid, reject_counts = filter_live_listings(raw_listings, item, language=language, condition=condition, config=config)
    required = max(int(config.sample_size or 5), 1)
    sample = valid[:required]
    live_low = sample[0]["price"] if sample else None
    live_avg = round_money(sum(row["price"] for row in sample) / required) if len(sample) >= required else None
    fetched_at = payload_fetched_at(payload)
    live_status = "resolved" if live_avg is not None else "insufficient_sample"
    reason = "live_avg5" if live_status == "resolved" and required == 5 else f"live_avg{required}" if live_status == "resolved" else f"sin_muestra_suficiente:{len(sample)}/{required}"

    updated = dict(market)
    updated.update({
        "status": live_status,
        "source": HYBRID_PRICE_SOURCE,
        "pricingMode": "hybrid",
        "currency": text(market.get("currency") or "EUR"),
        "unit": live_avg,
        "selected": live_avg,
        "selectedLabel": f"avg{required}_live" if live_avg is not None else None,
        "liveLow": live_low,
        "liveAvg5": live_avg if required == 5 else None,
        "liveRecommended": live_avg,
        "liveSampleSize": len(sample),
        "liveValidListings": len(valid),
        "liveRawListings": len(raw_listings),
        "matchReason": f"{text(market.get('matchReason'))};{reason}".strip(";"),
        "lastUpdated": fetched_at,
        "fallbackPriceGuide": priceguide_snapshot(market),
        "listingFilter": live_filter_payload(language, condition, config),
        "liveListings": {
            "status": live_status,
            "reason": reason,
            "filter": live_filter_payload(language, condition, config),
            "rawCount": len(raw_listings),
            "validCount": len(valid),
            "requiredSampleSize": required,
            "rejectCounts": reject_counts,
            "sample": sample,
            "fetchedAt": fetched_at,
        },
    })
    if live_status != "resolved":
        updated["unit"] = None
        updated["selected"] = None
        updated["selectedLabel"] = None
    return updated


def apply_live_listings_price(
    item: Dict[str, Any],
    product: Optional[CatalogProduct],
    market: Dict[str, Any],
    config: LiveListingsConfig,
) -> Dict[str, Any]:
    if not config.enabled:
        return market
    if text(market.get("status")) != "resolved" or not product:
        return market

    language = resolve_listing_language(item, config.language)
    condition = condition_slug(config.condition, default="nm")
    if not language:
        return live_problem_market_payload(
            market,
            status="unsupported_language",
            reason=f"idioma_no_soportado:{text(item.get('language')) or 'vacio'}",
            language=text(item.get("language")) or "auto",
            condition=condition,
            config=config,
        )

    try:
        payload = download_live_listing_payload(product.id_product, language=language, condition=condition, config=config)
    except Exception as exc:  # noqa: BLE001 - se informa en JSON y se sigue con el resto del lote.
        return live_problem_market_payload(
            market,
            status="live_error",
            reason=f"live_error:{type(exc).__name__}:{str(exc)[:180]}",
            language=language,
            condition=condition,
            config=config,
        )

    return build_live_market_payload(item, market, payload, language=language, condition=condition, config=config)


def scrape_filter_payload(language: str, condition: str, config: ScrapeListingsConfig) -> Dict[str, Any]:
    payload = live_filter_payload(language, condition, config)
    payload.update({
        "source": "cardmarket_public_page",
        "siteLanguage": text(config.site_language or "en"),
        "requireLanguage": bool(config.require_language),
        "requireCondition": bool(config.require_condition),
    })
    return payload




def priceguide_fallback_values(market: Dict[str, Any]) -> Tuple[Optional[float], Optional[str]]:
    snapshot = priceguide_snapshot(market)
    value = to_number(snapshot.get("unit") or snapshot.get("selected"))
    label = text(snapshot.get("selectedLabel")) or None
    if value is not None:
        return round_money(value), label
    for key in PREFERRED_PRICE_ORDER:
        value = to_number(snapshot.get(key))
        if value is not None:
            return round_money(value), key
    return None, None


def fallback_status(status: str) -> str:
    return f"{status}_fallback" if status and not status.endswith("_fallback") else status


def apply_scrape_priceguide_fallback(
    updated: Dict[str, Any],
    original_market: Dict[str, Any],
    *,
    status: str,
    reason: str,
    config: ScrapeListingsConfig,
) -> Dict[str, Any]:
    # Solo se usa fallback cuando el problema es tecnico del scraping.
    # Si el scrape funciona pero no hay 5 ofertas validas, se respeta "Sin muestra suficiente".
    fallback_allowed_statuses = {"scrape_blocked", "scrape_error", "scrape_no_product_page", "scrape_skipped_limit"}
    fallback_unit, fallback_label = priceguide_fallback_values(original_market)
    if (
        not getattr(config, "fallback_to_priceguide", True)
        or status not in fallback_allowed_statuses
        or fallback_unit is None
        or fallback_unit <= 0
    ):
        updated["unit"] = None
        updated["selected"] = None
        updated["selectedLabel"] = None
        updated["fallbackUsed"] = False
        return updated
    updated["status"] = fallback_status(status)
    updated["source"] = f"{SCRAPE_PRICE_SOURCE} (fallback Data Tables)"
    updated["pricingMode"] = "scrape_fallback"
    updated["unit"] = fallback_unit
    updated["selected"] = fallback_unit
    updated["selectedLabel"] = f"{fallback_label or 'priceguide'}_fallback"
    updated["fallbackUsed"] = True
    updated["fallbackReason"] = reason
    updated["matchReason"] = f"{text(updated.get('matchReason'))};fallback_priceguide".strip(";")
    return updated

def scrape_problem_market_payload(
    market: Dict[str, Any],
    *,
    status: str,
    reason: str,
    language: str,
    condition: str,
    config: ScrapeListingsConfig,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    listing_filter = scrape_filter_payload(language, condition, config)
    extra = extra or {}
    raw_count = int(extra.get("rawCount") or 0)
    product_url_value = text(extra.get("productUrl") or market.get("productUrl")) or None
    updated = dict(market)
    cardmarket_payload = dict(updated.get("cardmarket") or {})
    if product_url_value:
        cardmarket_payload["scrapeUrl"] = product_url_value
    top_status = status
    updated.update({
        "status": top_status,
        "source": SCRAPE_PRICE_SOURCE,
        "pricingMode": "scrape",
        "unit": None,
        "selected": None,
        "selectedLabel": None,
        "matchReason": reason,
        "lastUpdated": now_iso(),
        "productUrl": product_url_value or updated.get("productUrl"),
        "cardmarket": cardmarket_payload or updated.get("cardmarket"),
        "fallbackPriceGuide": priceguide_snapshot(market),
        "listingFilter": listing_filter,
        "liveSampleSize": 0,
        "liveValidListings": 0,
        "liveRawListings": raw_count,
        "scrapeSampleSize": 0,
        "scrapeValidListings": 0,
        "scrapeRawListings": raw_count,
        "scrapeLow": None,
        "scrapeAvg5": None,
        "scrapeRecommended": None,
        "scrapeProductUrl": product_url_value,
        "liveListings": {
            "status": status,
            "reason": reason,
            "filter": listing_filter,
            "rawCount": raw_count,
            "validCount": 0,
            "sample": [],
        },
        "scrapeListings": {
            "status": status,
            "reason": reason,
            "filter": listing_filter,
            "rawCount": raw_count,
            "validCount": 0,
            "sample": [],
            "details": extra.get("details"),
        },
    })
    if extra:
        updated["scrapeListings"].update({k: v for k, v in extra.items() if k not in {"rawCount"}})
    return apply_scrape_priceguide_fallback(updated, market, status=status, reason=reason, config=config)


def build_scraped_market_payload(
    item: Dict[str, Any],
    market: Dict[str, Any],
    payload: Dict[str, Any],
    *,
    language: str,
    condition: str,
    config: ScrapeListingsConfig,
) -> Dict[str, Any]:
    raw_listings = extract_live_listings(payload)
    valid, reject_counts = filter_live_listings(raw_listings, item, language=language, condition=condition, config=config)
    required = max(int(config.sample_size or 5), 1)
    sample = valid[:required]
    scrape_low = sample[0]["price"] if sample else None
    scrape_avg = round_money(sum(row["price"] for row in sample) / required) if len(sample) >= required else None
    fetched_at = payload_fetched_at(payload)
    scrape_status = "resolved" if scrape_avg is not None else "insufficient_sample"
    reason = (
        "scrape_avg5" if scrape_status == "resolved" and required == 5
        else f"scrape_avg{required}" if scrape_status == "resolved"
        else f"sin_muestra_suficiente:{len(sample)}/{required}"
    )
    product_url_value = text(payload.get("productUrl") or market.get("productUrl")) or None
    listing_filter = scrape_filter_payload(language, condition, config)
    cardmarket_payload = dict(market.get("cardmarket") or {})
    if product_url_value:
        cardmarket_payload["url"] = product_url_value
        cardmarket_payload["scrapeUrl"] = product_url_value

    updated = dict(market)
    updated.update({
        "status": scrape_status,
        "source": SCRAPE_PRICE_SOURCE,
        "pricingMode": "scrape",
        "currency": text(market.get("currency") or "EUR"),
        "unit": scrape_avg,
        "selected": scrape_avg,
        "selectedLabel": f"avg{required}_scrape" if scrape_avg is not None else None,
        "productUrl": product_url_value or market.get("productUrl"),
        "cardmarket": cardmarket_payload or market.get("cardmarket"),
        "liveLow": scrape_low,
        "liveAvg5": scrape_avg if required == 5 else None,
        "liveRecommended": scrape_avg,
        "liveSampleSize": len(sample),
        "liveValidListings": len(valid),
        "liveRawListings": len(raw_listings),
        "scrapeLow": scrape_low,
        "scrapeAvg5": scrape_avg if required == 5 else None,
        "scrapeRecommended": scrape_avg,
        "scrapeSampleSize": len(sample),
        "scrapeValidListings": len(valid),
        "scrapeRawListings": len(raw_listings),
        "scrapeProductUrl": product_url_value,
        "matchReason": f"{text(market.get('matchReason'))};{reason}".strip(";"),
        "lastUpdated": fetched_at,
        "fallbackPriceGuide": priceguide_snapshot(market),
        "listingFilter": listing_filter,
        "liveListings": {
            "status": scrape_status,
            "reason": reason,
            "filter": listing_filter,
            "rawCount": len(raw_listings),
            "validCount": len(valid),
            "requiredSampleSize": required,
            "rejectCounts": reject_counts,
            "sample": sample,
            "fetchedAt": fetched_at,
            "productUrl": product_url_value,
        },
        "scrapeListings": {
            "status": scrape_status,
            "reason": reason,
            "filter": listing_filter,
            "rawCount": len(raw_listings),
            "validCount": len(valid),
            "requiredSampleSize": required,
            "rejectCounts": reject_counts,
            "sample": sample,
            "fetchedAt": fetched_at,
            "productUrl": product_url_value,
            "details": payload.get("details"),
            "meta": payload.get("meta"),
        },
    })
    if scrape_status != "resolved":
        updated = apply_scrape_priceguide_fallback(updated, market, status=scrape_status, reason=reason, config=config)
    else:
        updated["fallbackUsed"] = False
    return updated


def apply_scraped_listings_price(
    item: Dict[str, Any],
    product: Optional[CatalogProduct],
    market: Dict[str, Any],
    config: ScrapeListingsConfig,
) -> Dict[str, Any]:
    if not config.enabled:
        return market
    if text(market.get("status")) != "resolved" or not product:
        return market

    language = resolve_listing_language(item, config.language)
    condition = condition_slug(config.condition, default="nm")
    if not language:
        return scrape_problem_market_payload(
            market,
            status="unsupported_language",
            reason=f"idioma_no_soportado:{text(item.get('language')) or 'vacio'}",
            language=text(item.get("language")) or "auto",
            condition=condition,
            config=config,
        )

    try:
        payload = download_scraped_listing_payload(item, product, language=language, condition=condition, config=config)
    except ScrapeBlockedError as exc:
        return scrape_problem_market_payload(
            market,
            status="scrape_blocked",
            reason=f"scrape_blocked:{str(exc)[:180]}",
            language=language,
            condition=condition,
            config=config,
        )
    except ScrapeNoProductPageError as exc:
        return scrape_problem_market_payload(
            market,
            status="scrape_no_product_page",
            reason=f"scrape_no_product_page:{str(exc)[:180]}",
            language=language,
            condition=condition,
            config=config,
        )
    except Exception as exc:  # noqa: BLE001 - se informa en JSON y se sigue con el resto del lote.
        return scrape_problem_market_payload(
            market,
            status="scrape_error",
            reason=f"scrape_error:{type(exc).__name__}:{str(exc)[:180]}",
            language=language,
            condition=condition,
            config=config,
        )

    return build_scraped_market_payload(item, market, payload, language=language, condition=condition, config=config)


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
    require_priceguide: bool = True,
    strict_matching: bool = False,
    scryfall_config: Optional[ScryfallCardmarketConfig] = None,
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
        if not market["unit"] and require_priceguide:
            market["status"] = "unmatched"
            market["matchReason"] = "override_sin_precio"
        return market, [candidate_to_report(product, max(score, 100), reasons + ["override"])]

    sf_product, sf_info = resolve_scryfall_cardmarket_product(item, catalog, scryfall_config)
    if sf_product:
        score, reasons = candidate_score(item, sf_product)
        score = max(score, 100.0)
        reason = ";".join(["scryfall_cardmarket_id"] + reasons)
        market = market_price_payload(item, sf_product, score, "resolved", reason)
        market["source"] = SCRYFALL_CARDMARKET_SOURCE
        market["scryfallResolver"] = sf_info
        if not market["unit"] and require_priceguide:
            market["status"] = "unmatched"
            market["matchReason"] = "scryfall_cardmarket_id_sin_priceguide"
        return market, [candidate_to_report(sf_product, score, reasons + ["scryfall_cardmarket_id"])]

    slug = game_slug_for_tcg(item.get("tcg"), item)

    candidate_pools: List[CatalogProduct] = []
    if slug in catalog.products_by_game:
        candidate_pools.extend(catalog.search_candidates(item, slug))
    # Accessories como pool adicional para productos que parezcan accesorios.
    if is_sealed_item(item) and slug != "accessories":
        candidate_pools.extend(catalog.search_candidates(item, "accessories", limit=350))

    # Deduplicado conservando el orden de prioridad del pre-filtro.
    seen_candidate_ids: Set[int] = set()
    unique_candidate_pools: List[CatalogProduct] = []
    for product in candidate_pools:
        if product.id_product not in seen_candidate_ids:
            unique_candidate_pools.append(product)
            seen_candidate_ids.add(product.id_product)

    scored: List[Tuple[float, CatalogProduct, List[str]]] = []
    for product in unique_candidate_pools:
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

    if (not has_price or not has_selected_price) and require_priceguide:
        return empty_market_payload("unmatched", "candidato_sin_priceguide", candidate_reports), candidate_reports

    if strict_matching:
        strict_ok, strict_reason = strict_match_check(item, best_product)
        if not strict_ok:
            exact_same_name_close = sum(
                1 for score, product, _reasons in top
                if normalize(product.name) == normalize(best_product.name) and score >= best_score - 3
            )
            # Las Data Tables actuales incluyen idExpansion pero a menudo no traen expansionName.
            # Para productos con nombre exacto y sin otro candidato equivalente, aceptamos el match
            # y dejamos rastro explicito. Los nombres repetidos siguen quedando como ambiguos/no match
            # salvo que Scryfall haya dado el idProduct exacto antes.
            if strict_reason == "edicion_no_confirmada" and exact_same_name_close <= 1 and best_score >= min_confidence:
                strict_ok = True
                strict_reason = "match_estricto_nombre_unico_sin_expansionName"
            else:
                return empty_market_payload("unmatched", strict_reason, candidate_reports), candidate_reports
        best_reasons = best_reasons + [strict_reason]

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
    live_config: Optional[LiveListingsConfig] = None,
    scrape_config: Optional[ScrapeListingsConfig] = None,
    scryfall_config: Optional[ScryfallCardmarketConfig] = None,
    require_priceguide: bool = True,
    strict_matching: bool = False,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    price_items: List[Dict[str, Any]] = []
    updated_items: List[Dict[str, Any]] = []
    report_rows: List[Dict[str, Any]] = []
    live_attempts = 0
    scrape_attempts = 0

    total_items = len(items)
    if total_items:
        log(f"Cruzando {'wishlist' if wishlist else 'coleccion'}: {total_items} elementos")

    for index, item in enumerate(items, start=1):
        if index == 1 or index % 25 == 0 or index == total_items:
            log(f"Matching {'wishlist' if wishlist else 'coleccion'}: {index}/{total_items}")
        item_id = text(item.get("id"))
        market, candidates = match_item(
            item,
            catalog,
            overrides,
            min_confidence=min_confidence,
            wishlist=wishlist,
            require_priceguide=require_priceguide,
            strict_matching=strict_matching,
            scryfall_config=scryfall_config,
        )
        product_for_pricing: Optional[CatalogProduct] = None
        if (live_config and live_config.enabled) or (scrape_config and scrape_config.enabled):
            try:
                product_id = int(market.get("productId"))
                product_for_pricing = catalog.products_by_id.get(product_id)
            except (TypeError, ValueError):
                product_for_pricing = None

        if live_config and live_config.enabled and market.get("status") == "resolved":
            if live_config.max_items and live_attempts >= live_config.max_items:
                market = live_problem_market_payload(
                    market,
                    status="live_skipped_limit",
                    reason=f"limite_live_pruebas:{live_config.max_items}",
                    language=resolve_listing_language(item, live_config.language) or text(item.get("language")) or "auto",
                    condition=condition_slug(live_config.condition, default="nm"),
                    config=live_config,
                )
            else:
                live_attempts += 1
                market = apply_live_listings_price(item, product_for_pricing, market, live_config)

        if scrape_config and scrape_config.enabled and market.get("status") == "resolved":
            if scrape_config.max_items and scrape_attempts >= scrape_config.max_items:
                market = scrape_problem_market_payload(
                    market,
                    status="scrape_skipped_limit",
                    reason=f"limite_scrape_pruebas:{scrape_config.max_items}",
                    language=resolve_listing_language(item, scrape_config.language) or text(item.get("language")) or "auto",
                    condition=condition_slug(scrape_config.condition, default="nm"),
                    config=scrape_config,
                )
            else:
                scrape_attempts += 1
                market = apply_scraped_listings_price(item, product_for_pricing, market, scrape_config)

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
            "source": market.get("source"),
            "pricingMode": market.get("pricingMode"),
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
            "listingLanguage": (market.get("listingFilter") or {}).get("language"),
            "listingCondition": (market.get("listingFilter") or {}).get("condition"),
            "liveSampleSize": market.get("liveSampleSize"),
            "liveValidListings": market.get("liveValidListings"),
            "liveRawListings": market.get("liveRawListings"),
            "liveLow": market.get("liveLow"),
            "scrapeSampleSize": market.get("scrapeSampleSize"),
            "scrapeValidListings": market.get("scrapeValidListings"),
            "scrapeRawListings": market.get("scrapeRawListings"),
            "scrapeLow": market.get("scrapeLow"),
            "scrapeProductUrl": market.get("scrapeProductUrl"),
            "scrapeStatus": (market.get("scrapeListings") or {}).get("status"),
            "scrapeReason": (market.get("scrapeListings") or {}).get("reason"),
            "fallbackPriceGuideUnit": (market.get("fallbackPriceGuide") or {}).get("unit"),
            "fallbackUsed": market.get("fallbackUsed"),
            "fallbackReason": market.get("fallbackReason"),
            "scryfallResolverStatus": (market.get("scryfallResolver") or {}).get("status"),
            "scryfallCardmarketId": (market.get("scryfallResolver") or {}).get("idProduct"),
            "scryfallSet": (market.get("scryfallResolver") or {}).get("scryfallSet"),
            "scryfallCollectorNumber": (market.get("scryfallResolver") or {}).get("scryfallCollectorNumber"),
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
    fallback_resolved = sum(count for status, count in status_counts.items() if status.endswith("_fallback"))
    return {
        "totalItems": len(items),
        "resolved": status_counts.get("resolved", 0) + fallback_resolved,
        "resolvedDirect": status_counts.get("resolved", 0),
        "resolvedFallback": fallback_resolved,
        "ambiguous": status_counts.get("ambiguous", 0),
        "unmatched": status_counts.get("unmatched", 0),
        "insufficientSample": status_counts.get("insufficient_sample", 0) + status_counts.get("insufficient_sample_fallback", 0),
        "unsupportedLanguage": status_counts.get("unsupported_language", 0) + status_counts.get("unsupported_language_fallback", 0),
        "liveError": status_counts.get("live_error", 0),
        "scrapeError": status_counts.get("scrape_error", 0) + status_counts.get("scrape_error_fallback", 0),
        "scrapeBlocked": status_counts.get("scrape_blocked", 0) + status_counts.get("scrape_blocked_fallback", 0),
        "scrapeNoProductPage": status_counts.get("scrape_no_product_page", 0) + status_counts.get("scrape_no_product_page_fallback", 0),
        "scrapeSkippedLimit": status_counts.get("scrape_skipped_limit", 0) + status_counts.get("scrape_skipped_limit_fallback", 0),
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


def update_portfolio_payload(
    portfolio: Dict[str, Any],
    updated_cards: List[Dict[str, Any]],
    market_summary: Dict[str, Any],
    *,
    source: str = "Cardmarket Data Tables",
    pricing_mode: str = "datatables",
) -> Dict[str, Any]:
    payload = dict(portfolio)
    payload["cards"] = updated_cards
    metadata = dict(payload.get("metadata") or {})
    metadata["marketPrices"] = {
        "source": source,
        "pricingMode": pricing_mode,
        "generatedAt": now_iso(),
        "summary": market_summary,
    }
    payload["metadata"] = metadata
    return payload


def update_wishlist_payload(
    wishlist: Dict[str, Any],
    updated_items: List[Dict[str, Any]],
    market_summary: Dict[str, Any],
    *,
    source: str = "Cardmarket Data Tables",
    pricing_mode: str = "datatables",
) -> Dict[str, Any]:
    payload = dict(wishlist)
    payload["items"] = updated_items
    metadata = dict(payload.get("metadata") or {})
    metadata["marketPrices"] = {
        "source": source,
        "pricingMode": pricing_mode,
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
    parser = argparse.ArgumentParser(description="Actualiza precios con Cardmarket Data Tables y V7 scraping directo.")
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
    parser.add_argument("--pricing-mode", choices=["datatables", "scrape", "hybrid"], default="datatables", help="datatables usa price guides; scrape usa idProduct + pagina publica Cardmarket; hybrid usa proveedor live legacy")
    parser.add_argument("--live-api-base", default=DEFAULT_LIVE_API_BASE, help="Base del proveedor live. Puede incluir {id} como plantilla")
    parser.add_argument("--live-api-key-env", default=DEFAULT_LIVE_API_KEY_ENV, help="Variable de entorno/secreto que contiene la API key live")
    parser.add_argument("--live-api-key", default="", help="API key live directa. Mejor usar --live-api-key-env o un secreto de GitHub")
    parser.add_argument("--live-api-key-query-param", default="", help="Nombre del query param si el proveedor no acepta X-API-Key")
    parser.add_argument("--listing-language", default="auto", help="auto usa el idioma del item; o fuerza english/spanish/japanese/etc.")
    parser.add_argument("--listing-condition", default="nm", help="Condicion minima para listings: mt,nm,ex,gd,lp,pl,po")
    parser.add_argument("--listing-sample-size", type=int, default=5, help="Numero de ofertas validas para la media recomendada")
    parser.add_argument("--exclude-uk", action=argparse.BooleanOptionalAction, default=True, help="Excluye vendedores de Reino Unido")
    parser.add_argument("--require-europe", action=argparse.BooleanOptionalAction, default=True, help="Solo acepta listings con pais europeo conocido")
    parser.add_argument("--live-cache", default=".cache/cardmarket-live", help="Carpeta de cache para respuestas live")
    parser.add_argument("--live-cache-hours", type=float, default=1.0, help="Horas de validez de cache live")
    parser.add_argument("--force-live-download", action="store_true", help="Redescarga listings live aunque exista cache reciente")
    parser.add_argument("--live-sleep", type=float, default=0.35, help="Pausa entre llamadas live")
    parser.add_argument("--live-timeout", type=int, default=35, help="Timeout en segundos para el proveedor live")
    parser.add_argument("--max-live-items", type=int, default=0, help="Limite de elementos live para pruebas; 0 = todos")
    parser.add_argument("--scrape-site-language", default="en", help="Idioma de la web Cardmarket para scraping")
    parser.add_argument("--scrape-cache", default=".cache/cardmarket-scrape", help="Carpeta de cache HTML scraping")
    parser.add_argument("--scrape-cache-hours", type=float, default=2.0, help="Horas de validez de cache scraping")
    parser.add_argument("--force-scrape-download", action="store_true", help="Redescarga HTML scraping aunque exista cache reciente")
    parser.add_argument("--scrape-sleep", type=float, default=1.2, help="Pausa entre requests scraping")
    parser.add_argument("--scrape-timeout", type=int, default=45, help="Timeout en segundos para scraping")
    parser.add_argument("--max-scrape-items", type=int, default=0, help="Limite de elementos scrape para pruebas; 0 = todos")
    parser.add_argument("--scrape-user-agent", default=DEFAULT_SCRAPE_USER_AGENT, help="User-Agent para scraping")
    parser.add_argument("--scrape-accept-language", default="en-US,en;q=0.9,es;q=0.8", help="Accept-Language para scraping")
    parser.add_argument("--cardmarket-cookie-env", default=DEFAULT_CARDMARKET_COOKIE_ENV, help="Variable de entorno opcional con la cabecera Cookie de Cardmarket")
    parser.add_argument("--cardmarket-cookie", default="", help="Cookie directa opcional; mejor usar una variable de entorno/secreto")
    parser.add_argument("--debug-scrape-html", action="store_true", help="Guarda HTML bloqueado para depuracion")
    parser.add_argument("--scrape-require-language", action=argparse.BooleanOptionalAction, default=True, help="Exige idioma conocido en cada listing scrapeado")
    parser.add_argument("--scrape-require-condition", action=argparse.BooleanOptionalAction, default=True, help="Exige condicion conocida en cada listing scrapeado")
    parser.add_argument("--no-scrape-search-fallback", dest="scrape_search_fallback", action="store_false", help="No buscar URL alternativa si la URL construida no es pagina de producto")
    parser.set_defaults(scrape_search_fallback=True)
    parser.add_argument("--scrape-fallback-to-priceguide", action=argparse.BooleanOptionalAction, default=True, help="Si Cardmarket bloquea el scraping, conserva el precio Data Tables como fallback transparente")
    parser.add_argument("--scryfall-cardmarket-match", action=argparse.BooleanOptionalAction, default=True, help="Usa Scryfall para obtener idProduct Cardmarket exacto de MTG cuando sea posible")
    parser.add_argument("--scryfall-cache", default=".cache/scryfall-cardmarket", help="Carpeta de cache para resoluciones Scryfall -> idProduct")
    parser.add_argument("--scryfall-cache-hours", type=float, default=24 * 14, help="Horas de validez de cache Scryfall")
    parser.add_argument("--scryfall-sleep", type=float, default=0.25, help="Pausa entre llamadas a Scryfall en segundos")
    parser.add_argument("--scryfall-max-retries", type=int, default=4, help="Reintentos ante HTTP 429/5xx de Scryfall")
    parser.add_argument("--force-scryfall-download", action="store_true", help="Redescarga resoluciones Scryfall aunque exista cache")
    parser.add_argument("--strict-matching", action=argparse.BooleanOptionalAction, default=None, help="Exige match estricto de nombre/edicion. Por defecto se activa en hybrid/scrape")
    args = parser.parse_args(argv)

    portfolio_path = Path(args.portfolio)
    wishlist_path = Path(args.wishlist)
    out_dir = Path(args.out)
    cache_dir = Path(args.cache)
    overrides_path = Path(args.overrides)

    live_config = LiveListingsConfig(
        enabled=args.pricing_mode == "hybrid",
        base_url=args.live_api_base,
        api_key_env=args.live_api_key_env,
        api_key=args.live_api_key,
        api_key_query_param=args.live_api_key_query_param,
        language=args.listing_language,
        condition=condition_slug(args.listing_condition, default="nm"),
        sample_size=max(int(args.listing_sample_size or 5), 1),
        exclude_uk=bool(args.exclude_uk),
        require_europe=bool(args.require_europe),
        cache_dir=Path(args.live_cache),
        cache_hours=float(args.live_cache_hours),
        force=bool(args.force_live_download),
        sleep=float(args.live_sleep),
        timeout_seconds=int(args.live_timeout),
        max_items=max(int(args.max_live_items or 0), 0),
    )
    scrape_config = ScrapeListingsConfig(
        enabled=args.pricing_mode == "scrape",
        site_language=args.scrape_site_language,
        language=args.listing_language,
        condition=condition_slug(args.listing_condition, default="nm"),
        sample_size=max(int(args.listing_sample_size or 5), 1),
        exclude_uk=bool(args.exclude_uk),
        require_europe=bool(args.require_europe),
        require_language=bool(args.scrape_require_language),
        require_condition=bool(args.scrape_require_condition),
        cache_dir=Path(args.scrape_cache),
        cache_hours=float(args.scrape_cache_hours),
        force=bool(args.force_scrape_download),
        sleep=float(args.scrape_sleep),
        timeout_seconds=int(args.scrape_timeout),
        max_items=max(int(args.max_scrape_items or 0), 0),
        user_agent=args.scrape_user_agent,
        accept_language=args.scrape_accept_language,
        cookie_env=args.cardmarket_cookie_env,
        cookie=args.cardmarket_cookie,
        debug_html=bool(args.debug_scrape_html),
        search_fallback=bool(args.scrape_search_fallback),
        fallback_to_priceguide=bool(args.scrape_fallback_to_priceguide),
    )
    scryfall_config = ScryfallCardmarketConfig(
        enabled=bool(args.scryfall_cardmarket_match),
        cache_dir=Path(args.scryfall_cache),
        cache_hours=float(args.scryfall_cache_hours),
        force=bool(args.force_scryfall_download),
        sleep=float(args.scryfall_sleep),
        max_retries=int(args.scryfall_max_retries),
    )
    if live_config.enabled and not live_config.resolved_api_key():
        parser.error(f"--pricing-mode hybrid requiere una clave live en {live_config.api_key_env} o --live-api-key")
    strict_matching = bool(args.strict_matching) if args.strict_matching is not None else args.pricing_mode in {"hybrid", "scrape"}
    require_priceguide = args.pricing_mode == "datatables"
    output_source = (
        HYBRID_PRICE_SOURCE if live_config.enabled
        else SCRAPE_PRICE_SOURCE if scrape_config.enabled
        else "Cardmarket Data Tables"
    )
    active_listing_config: Any = scrape_config if scrape_config.enabled else live_config

    portfolio = load_json(portfolio_path, {"metadata": {}, "cards": []})
    wishlist = load_json(wishlist_path, {"metadata": {}, "items": []})
    ensure_override_file(overrides_path)
    overrides = load_json(overrides_path, {"items": {}, "wishlistItems": {}})

    extra_games = [normalize(part).replace(" ", "") for part in args.games.split(",") if part.strip()]
    slugs = games_from_data(portfolio, wishlist, extra_games)
    log(f"Descargando tablas Cardmarket para: {', '.join(slugs)}")
    catalog = load_cardmarket_catalog(slugs, cache_dir, force_download=args.force_download)
    log(f"Productos cargados: {len(catalog.products_by_id):,}; price guide: {len(catalog.price_by_id):,}")
    if scryfall_config.enabled:
        log("Resolver Scryfall activo: usa cardmarket_id para MTG singles antes del matching textual")
    if live_config.enabled:
        log(
            "Modo hybrid activo: idProduct por Data Tables + listings live "
            f"({args.listing_language}/{live_config.condition}, muestra={live_config.sample_size}, exclude_uk={live_config.exclude_uk})"
        )
    if scrape_config.enabled:
        log(
            "Modo scrape V7.1 activo: idProduct por Data Tables/Scryfall + pagina publica Cardmarket "
            f"({args.listing_language}/{scrape_config.condition}, muestra={scrape_config.sample_size}, exclude_uk={scrape_config.exclude_uk}, fallback_priceguide={scrape_config.fallback_to_priceguide})"
        )
    if scryfall_config.enabled:
        log(f"Resolucion Scryfall -> idProduct Cardmarket activa para MTG singles; cache={scryfall_config.cache_dir}")

    price_items, updated_cards, report_collection = update_collection_items(
        list(portfolio.get("cards") or []),
        catalog,
        overrides,
        min_confidence=args.min_confidence,
        wishlist=False,
        live_config=live_config,
        scrape_config=scrape_config,
        scryfall_config=scryfall_config,
        require_priceguide=require_priceguide,
        strict_matching=strict_matching,
    )
    wishlist_price_items, updated_wishlist_items, report_wishlist = update_collection_items(
        list(wishlist.get("items") or []),
        catalog,
        overrides,
        min_confidence=args.min_confidence,
        wishlist=True,
        live_config=live_config,
        scrape_config=scrape_config,
        scryfall_config=scryfall_config,
        require_priceguide=require_priceguide,
        strict_matching=strict_matching,
    )

    market_summary = summary_for(price_items)
    wishlist_summary = summary_for(wishlist_price_items)
    market_payload = {
        "metadata": {
            "source": output_source,
            "pricingMode": args.pricing_mode,
            "generatedAt": now_iso(),
            "downloaded": catalog.downloaded,
            "minConfidence": args.min_confidence,
            "strictMatching": strict_matching,
            "requirePriceGuideBeforePricing": require_priceguide,
            "listingFilter": {
                "language": args.listing_language,
                "condition": active_listing_config.condition,
                "sampleSize": active_listing_config.sample_size,
                "excludeUK": active_listing_config.exclude_uk,
                "requireEurope": active_listing_config.require_europe,
            },
            "liveProvider": {
                "enabled": live_config.enabled,
                "baseUrl": live_config.base_url,
                "apiKeyEnv": live_config.api_key_env,
                "apiKeyQueryParam": live_config.api_key_query_param or None,
                "cacheHours": live_config.cache_hours,
            },
            "scrape": {
                "enabled": scrape_config.enabled,
                "siteLanguage": scrape_config.site_language,
                "cacheHours": scrape_config.cache_hours,
                "cacheDir": str(scrape_config.cache_dir),
                "cookieEnv": scrape_config.cookie_env,
                "searchFallback": scrape_config.search_fallback,
                "requireLanguage": scrape_config.require_language,
                "requireCondition": scrape_config.require_condition,
                "fallbackToPriceGuide": scrape_config.fallback_to_priceguide,
            },
            "scryfallCardmarketMatch": {
                "enabled": scryfall_config.enabled,
                "cacheDir": str(scryfall_config.cache_dir),
                "cacheHours": scryfall_config.cache_hours,
            },
            "note": "V7.1 usa Scryfall como apoyo para resolver idProduct exacto en MTG cuando las Data Tables no traen expansionName; scrape usa la pagina publica del producto para listings filtrados. Si Cardmarket bloquea el scraping, se conserva de forma transparente el precio Data Tables como fallback.",
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
        updated_portfolio = update_portfolio_payload(
            portfolio, updated_cards, market_summary, source=output_source, pricing_mode=args.pricing_mode
        )
        save_json(portfolio_path, updated_portfolio)
        save_js(portfolio_path.with_suffix(".js"), "portfolioData", updated_portfolio)
    if args.update_wishlist:
        updated_wishlist = update_wishlist_payload(
            wishlist, updated_wishlist_items, wishlist_summary, source=output_source, pricing_mode=args.pricing_mode
        )
        save_json(wishlist_path, updated_wishlist)
        save_js(wishlist_path.with_suffix(".js"), "wishlistData", updated_wishlist)

    log("Resumen coleccion:")
    log(json.dumps(market_summary, ensure_ascii=False, indent=2))
    if wishlist_price_items:
        log("Resumen wishlist:")
        log(json.dumps(wishlist_summary, ensure_ascii=False, indent=2))
    log(f"Generado: {out_dir / 'market-prices.json'}")
    log(f"Reporte:  {out_dir / 'cardmarket-matching-report.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
