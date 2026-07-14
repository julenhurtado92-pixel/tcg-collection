#!/usr/bin/env python3
"""Generate the current-stock collection dataset from the Excel source.

The Excel remains the source of truth. The generated web dataset keeps only
current owned stock after purchases/sales reconciliation, groups repeated
entries by TCG + name + edition + language + variant, and applies the configured EUR
unit-cost display threshold after aggregation.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import re
import unicodedata
import zipfile
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
import xml.etree.ElementTree as ET
from urllib.parse import quote

NS = {"main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
EXCEL_EPOCH = datetime(1899, 12, 30)
DEFAULT_EXCEL_NAMES = ["MI COLECCION TCGS.xlsx", "MI COLECCIÓN TCGS.xlsx"]
EPSILON = 1e-9
ONEPIECE_MATERIAL_HINTS = [
    "one piece", "monkey d luffy", "roronoa", "kaido", "donquixote",
    "eustass", "ultra deck the three brothers", "starter deck absolute justice",
    "starter deck one piece film",
]


def col_to_idx(cell_ref: str) -> int:
    match = re.match(r"([A-Z]+)", cell_ref)
    if not match:
        return 0
    idx = 0
    for char in match.group(1):
        idx = idx * 26 + ord(char) - 64
    return idx - 1


def safe_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def strip_accents(value: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFKD", value) if not unicodedata.combining(ch))


def norm(value: Any) -> str:
    text = strip_accents(str(value or "").lower())
    text = text.replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def parse_excluded_tcgs(value: str) -> set[str]:
    return {norm(part) for part in safe_text(value).split(",") if norm(part)}


def is_excluded_tcg(tcg: Any, excluded: set[str]) -> bool:
    normalized = norm(tcg)
    if not normalized:
        return False
    return normalized in excluded or normalized.replace(" ", "") in {entry.replace(" ", "") for entry in excluded}


def is_excluded_material(tx: dict[str, Any], excluded: set[str]) -> bool:
    if is_excluded_tcg(tx.get("tcg"), excluded):
        return True
    if "onepiece" not in {entry.replace(" ", "") for entry in excluded}:
        return False
    haystack = norm(" ".join([safe_text(tx.get("cardName")), safe_text(tx.get("edition")), safe_text(tx.get("name"))]))
    return any(norm(hint) in haystack for hint in ONEPIECE_MATERIAL_HINTS)


def as_float(value: Any, default: float = 0.0) -> float:
    if value is None or value == "":
        return default
    if isinstance(value, (int, float)):
        if math.isnan(float(value)) or math.isinf(float(value)):
            return default
        return float(value)
    raw = str(value).strip().replace("€", "").replace(" ", "")
    if "," in raw and "." in raw:
        raw = raw.replace(".", "").replace(",", ".")
    elif "," in raw:
        raw = raw.replace(",", ".")
    try:
        return float(raw)
    except ValueError:
        return default


def round_money(value: float) -> float:
    return round(float(value or 0), 2)


def round_qty(value: float) -> float:
    rounded = round(float(value or 0), 4)
    if abs(rounded - round(rounded)) < 0.0001:
        return float(round(rounded))
    return rounded


def excel_date_to_iso(value: Any) -> str:
    if value in (None, ""):
        return ""
    if isinstance(value, (int, float)):
        dt = EXCEL_EPOCH + timedelta(days=float(value))
        if dt.time().hour == 0 and dt.time().minute == 0 and dt.time().second == 0:
            return dt.date().isoformat()
        return dt.replace(microsecond=0).isoformat()
    return str(value)


def year_month_from_date(date_iso: str, fallback_year: Any = None, fallback_month: str = "") -> Tuple[Optional[int], str]:
    if date_iso:
        try:
            year = int(date_iso[:4])
            month_number = int(date_iso[5:7])
            return year, f"{year}-{month_number:02d}"
        except Exception:
            pass
    year = int(as_float(fallback_year)) if fallback_year not in (None, "") else None
    month = safe_text(fallback_month)
    return year, month


def load_shared_strings(zip_file: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in zip_file.namelist():
        return []
    root = ET.fromstring(zip_file.read("xl/sharedStrings.xml"))
    shared = []
    for item in root.findall("main:si", NS):
        text = "".join(
            (node.text or "")
            for node in item.iter("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}t")
        )
        shared.append(text)
    return shared


def sheet_path(zip_file: zipfile.ZipFile, sheet_name: str) -> str:
    workbook = ET.fromstring(zip_file.read("xl/workbook.xml"))
    rels = ET.fromstring(zip_file.read("xl/_rels/workbook.xml.rels"))
    rel_map = {rel.attrib["Id"]: rel.attrib["Target"] for rel in rels}
    for sheet in workbook.find("main:sheets", NS):
        if sheet.attrib.get("name") == sheet_name:
            rid = sheet.attrib[f"{{{REL_NS}}}id"]
            return "xl/" + rel_map[rid]
    raise KeyError(f"No se encontro la hoja {sheet_name!r}")


def cell_value(cell: ET.Element, shared_strings: list[str]) -> Any:
    cell_type = cell.attrib.get("t")
    value_node = cell.find("main:v", NS)
    inline_node = cell.find("main:is", NS)

    if cell_type == "inlineStr" and inline_node is not None:
        return "".join(
            (node.text or "")
            for node in inline_node.iter("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}t")
        )
    if value_node is None:
        return None
    raw = value_node.text
    if raw is None:
        return None
    if cell_type == "s":
        return shared_strings[int(raw)]
    if cell_type == "str":
        return raw
    try:
        number = float(raw)
        return int(number) if number.is_integer() else number
    except ValueError:
        return raw


def read_sheet_rows(excel_path: Path, sheet_name: str) -> list[tuple[int, list[Any]]]:
    with zipfile.ZipFile(excel_path) as zip_file:
        shared = load_shared_strings(zip_file)
        xml_path = sheet_path(zip_file, sheet_name)
        root = ET.fromstring(zip_file.read(xml_path))
        rows = []
        for row in root.findall(".//main:sheetData/main:row", NS):
            row_index = int(row.attrib["r"])
            values: list[Any] = []
            for cell in row.findall("main:c", NS):
                idx = col_to_idx(cell.attrib.get("r", "A1"))
                while len(values) <= idx:
                    values.append(None)
                values[idx] = cell_value(cell, shared)
            rows.append((row_index, values))
        return rows


def has_playset_marker(name: str) -> bool:
    return bool(re.search(r"\[\s*Playset\s*\]", name or "", flags=re.IGNORECASE))


def has_foil_marker(name: str) -> bool:
    return bool(re.search(r"\[\s*Foil\s*\]", name or "", flags=re.IGNORECASE))


def is_riftbound(tcg: Any) -> bool:
    return norm(tcg) == "riftbound"


def clean_display_name(name: str) -> str:
    cleaned = safe_text(name)
    cleaned = re.sub(r"\s*\[\s*Playset\s*\]\s*", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*\[\s*Foil\s*\]\s*", " ", cleaned, flags=re.IGNORECASE)
    # V.1 / V.2 / V.3 are cosmetic print versions. They are not separate stock buckets.
    cleaned = re.sub(r"\s*\(V\.\s*\d+[^)]*\)\s*", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def clean_scryfall_name(card_name: str) -> str:
    name = clean_display_name(card_name)
    name = re.sub(r"\s*\(V\.\d+[^)]*\)\s*", "", name, flags=re.IGNORECASE)
    name = re.sub(r"\s+", " ", name).strip()
    return name


def extract_variant_label(name: str, tcg: Any = "") -> str:
    # All non-foil print versions are grouped as Non-foil. All foil/showcase versions are grouped as Foil.
    return "Foil" if is_riftbound(tcg) or has_foil_marker(name) else "Non-foil"


def variant_key(name: str, tcg: Any = "") -> str:
    # Only Foil/Non-foil are used for grouping. V.1/V.2/showcase cosmetics are collapsed.
    return "foil" if is_riftbound(tcg) or has_foil_marker(name) else "nonfoil"


def build_scryfall_search_uri(card_name: str, tcg: str) -> str:
    if "magic" not in safe_text(tcg).lower():
        return ""
    query_name = clean_scryfall_name(card_name)
    if not query_name:
        return ""
    return "https://scryfall.com/search?as=grid&order=name&q=" + quote(f'!"{query_name}"')


def price_band(unit_value: float) -> str:
    if unit_value >= 250:
        return "250€+"
    if unit_value >= 100:
        return "100€ - 249,99€"
    if unit_value >= 50:
        return "50€ - 99,99€"
    if unit_value >= 20:
        return "20€ - 49,99€"
    if unit_value >= 10:
        return "10€ - 19,99€"
    return "<10€"


def status_from_row(row: list[Any], indexes: dict[str, int], column: str) -> Any:
    idx = indexes[column]
    return row[idx] if idx < len(row) else None


def make_transaction(row_index: int, row: list[Any], indexes: dict[str, int]) -> dict[str, Any]:
    def get(column: str) -> Any:
        return status_from_row(row, indexes, column)

    original_name = safe_text(get("Card Name"))
    display_name = clean_display_name(original_name)
    tcg = safe_text(get("TCG")) or "Sin TCG"
    edition = safe_text(get("Edition")) or "Sin edición"
    language = safe_text(get("Language")) or "Sin idioma"
    operation = safe_text(get("Tipo Operación")) or "Sin operación"
    quantity_raw = as_float(get("Quantity"), 0.0)
    playset_converted = has_playset_marker(original_name) and abs(quantity_raw - 1) < 0.0001
    quantity = 4.0 if playset_converted else quantity_raw
    total_raw = round_money(as_float(get("Total"), 0.0))
    sale_raw = round_money(as_float(get("Precio de venta"), 0.0)) if "Precio de venta" in indexes else 0.0
    operation_norm = norm(operation)
    is_purchase = operation_norm == "compra"
    is_sale = operation_norm == "venta"
    total_purchase_value = total_raw if is_purchase else 0.0
    sale_value = sale_raw or (total_raw if is_sale else 0.0)
    unit_value = round_money((total_purchase_value if is_purchase else sale_value) / quantity) if quantity > 0 else round_money(as_float(get("Unit Price"), 0.0))
    unit_purchase_value = round_money(total_purchase_value / quantity) if is_purchase and quantity > 0 else 0.0
    unit_sale_value = round_money(sale_value / quantity) if is_sale and quantity > 0 else 0.0
    date_iso = excel_date_to_iso(get("Date"))
    year, period = year_month_from_date(date_iso, get("Año"), safe_text(get("Mes")))
    group_key = "|".join([
        norm(tcg),
        norm(display_name),
        norm(edition),
        norm(language),
        variant_key(original_name, tcg),
    ])
    base_key = "|".join([norm(tcg), norm(display_name), norm(edition), norm(language)])
    loose_key = "|".join([norm(tcg), norm(display_name), norm(edition)])
    name_key = "|".join([norm(tcg), norm(display_name)])

    return {
        "id": f"excel-row-{row_index}",
        "sourceRow": row_index,
        "orderNumber": safe_text(get("Order Number")),
        "month": safe_text(get("Mes")),
        "year": year,
        "period": period,
        "date": date_iso,
        "sellerBuyer": safe_text(get("Seller / Buyer")),
        "originalName": original_name,
        "name": display_name,
        "cardName": display_name,
        "scryfallName": clean_scryfall_name(display_name),
        "edition": edition,
        "playset": safe_text(get("Playset")),
        "playsetConverted": playset_converted,
        "language": language,
        "variant": extract_variant_label(original_name, tcg),
        "variantKey": variant_key(original_name, tcg),
        "unitPurchaseValue": unit_purchase_value,
        "unitPrice": unit_purchase_value if is_purchase else unit_sale_value,
        "unitSaleValue": unit_sale_value,
        "quantity": round_qty(quantity),
        "rawQuantity": round_qty(quantity_raw),
        "totalPurchaseValue": total_purchase_value,
        "total": total_purchase_value if is_purchase else sale_value,
        "operation": operation,
        "operationNormalized": operation_norm,
        "saleValue": sale_value,
        "tcg": tcg,
        "priceBand": price_band(unit_purchase_value if is_purchase else unit_sale_value),
        "groupKey": group_key,
        "baseKey": base_key,
        "looseKey": loose_key,
        "nameKey": name_key,
    }


def create_group(tx: dict[str, Any]) -> dict[str, Any]:
    scryfall_uri = build_scryfall_search_uri(tx["cardName"], tx["tcg"])
    return {
        "id": "stock-" + re.sub(r"[^a-z0-9]+", "-", tx["groupKey"])[:110].strip("-"),
        "groupKey": tx["groupKey"],
        "baseKey": tx["baseKey"],
        "looseKey": tx["looseKey"],
        "nameKey": tx["nameKey"],
        "sourceRow": tx["sourceRow"],
        "sourceRows": [],
        "purchaseSourceRows": [],
        "saleSourceRows": [],
        "orderNumbers": [],
        "sellerBuyers": [],
        "name": tx["cardName"],
        "cardName": tx["cardName"],
        "scryfallName": tx["scryfallName"],
        "edition": tx["edition"],
        "language": tx["language"],
        "variant": tx["variant"],
        "variantKey": tx["variantKey"],
        "tcg": tx["tcg"],
        "date": tx["date"],
        "firstPurchaseDate": tx["date"],
        "lastPurchaseDate": tx["date"],
        "month": tx["month"],
        "year": tx["year"],
        "purchasedQuantity": 0.0,
        "soldQuantity": 0.0,
        "quantity": 0.0,
        "grossPurchaseValue": 0.0,
        "saleRevenue": 0.0,
        "stockCost": 0.0,
        "unitPurchaseValue": 0.0,
        "unitPrice": 0.0,
        "totalPurchaseValue": 0.0,
        "total": 0.0,
        "operation": "Stock actual",
        "priceBand": "<10€",
        "playsetConversions": 0,
        "purchaseCount": 0,
        "saleCount": 0,
        "purchaseHistory": [],
        "stockLots": [],
        "salesHistory": [],
        "images": {
            "small": "",
            "normal": "",
            "large": "",
            "artCrop": "",
            "status": "pending" if scryfall_uri else "not_applicable",
        },
        "scryfall": {"searchUri": scryfall_uri, "resolved": False},
        "marketPrice": {"average": None, "currency": "EUR", "sources": [], "lastUpdated": None, "status": "not_requested"},
    }


def add_purchase(group: dict[str, Any], tx: dict[str, Any]) -> None:
    qty = as_float(tx["quantity"])
    total = as_float(tx["totalPurchaseValue"])
    unit = round_money(total / qty) if qty > 0 else 0.0
    group["sourceRows"].append(tx["sourceRow"])
    group["purchaseSourceRows"].append(tx["sourceRow"])
    if tx["orderNumber"]:
        group["orderNumbers"].append(tx["orderNumber"])
    if tx["sellerBuyer"]:
        group["sellerBuyers"].append(tx["sellerBuyer"])
    group["purchasedQuantity"] += qty
    group["grossPurchaseValue"] += total
    group["purchaseCount"] += 1
    group["playsetConversions"] += 1 if tx["playsetConverted"] else 0
    if tx["date"]:
        dates = [d for d in [group.get("firstPurchaseDate"), group.get("lastPurchaseDate"), tx["date"]] if d]
        group["firstPurchaseDate"] = min(dates)
        group["lastPurchaseDate"] = max(dates)
        group["date"] = group["lastPurchaseDate"]
    lot = {
        "sourceRow": tx["sourceRow"],
        "date": tx["date"],
        "period": tx["period"],
        "year": tx["year"],
        "quantity": round_qty(qty),
        "remainingQuantity": round_qty(qty),
        "unitCost": unit,
        "totalCost": round_money(total),
        "remainingCost": round_money(total),
        "sellerBuyer": tx["sellerBuyer"],
        "orderNumber": tx["orderNumber"],
    }
    group["purchaseHistory"].append(lot)


def subtract_fifo(group: dict[str, Any], sale_qty: float) -> Tuple[float, float]:
    remaining_to_subtract = sale_qty
    removed_qty = 0.0
    removed_cost = 0.0
    lots = sorted(group["purchaseHistory"], key=lambda lot: (lot.get("date") or "9999", lot.get("sourceRow") or 0))
    for lot in lots:
        if remaining_to_subtract <= EPSILON:
            break
        lot_remaining = as_float(lot.get("remainingQuantity"))
        if lot_remaining <= EPSILON:
            continue
        take = min(lot_remaining, remaining_to_subtract)
        unit = as_float(lot.get("unitCost"))
        lot["remainingQuantity"] = round_qty(lot_remaining - take)
        lot["remainingCost"] = round_money(as_float(lot.get("remainingQuantity")) * unit)
        removed_qty += take
        removed_cost += take * unit
        remaining_to_subtract -= take
    return round_qty(removed_qty), round_money(removed_cost)


def add_sale(group: dict[str, Any], tx: dict[str, Any], method: str) -> dict[str, Any]:
    qty = as_float(tx["quantity"])
    sale_total = as_float(tx["saleValue"])
    removed_qty, removed_cost = subtract_fifo(group, qty)
    group["sourceRows"].append(tx["sourceRow"])
    group["saleSourceRows"].append(tx["sourceRow"])
    group["soldQuantity"] += qty
    group["saleRevenue"] += sale_total
    group["saleCount"] += 1
    sale_entry = {
        "sourceRow": tx["sourceRow"],
        "date": tx["date"],
        "period": tx["period"],
        "year": tx["year"],
        "quantity": round_qty(qty),
        "matchedQuantity": round_qty(removed_qty),
        "saleValue": round_money(sale_total),
        "estimatedCostRemoved": round_money(removed_cost),
        "method": method,
        "sellerBuyer": tx["sellerBuyer"],
        "orderNumber": tx["orderNumber"],
    }
    group["salesHistory"].append(sale_entry)
    return sale_entry


def build_indexes(groups: dict[str, dict[str, Any]]) -> dict[str, defaultdict[str, list[str]]]:
    indexes: dict[str, defaultdict[str, list[str]]] = {
        "baseKey": defaultdict(list),
        "looseKey": defaultdict(list),
        "nameKey": defaultdict(list),
    }
    for key, group in groups.items():
        indexes["baseKey"][group["baseKey"]].append(key)
        indexes["looseKey"][group["looseKey"]].append(key)
        indexes["nameKey"][group["nameKey"]].append(key)
    return indexes


def available_stock(group: dict[str, Any]) -> float:
    return max(0.0, as_float(group.get("purchasedQuantity")) - as_float(group.get("soldQuantity")))


def choose_candidate(candidate_keys: list[str], groups: dict[str, dict[str, Any]]) -> Optional[str]:
    if not candidate_keys:
        return None
    if len(candidate_keys) == 1:
        return candidate_keys[0]
    with_stock = [key for key in candidate_keys if available_stock(groups[key]) > EPSILON]
    if len(with_stock) == 1:
        return with_stock[0]
    if with_stock:
        return sorted(with_stock, key=lambda key: available_stock(groups[key]), reverse=True)[0]
    return sorted(candidate_keys, key=lambda key: as_float(groups[key].get("purchasedQuantity")), reverse=True)[0]


def match_sale(tx: dict[str, Any], groups: dict[str, dict[str, Any]], indexes: dict[str, defaultdict[str, list[str]]]) -> Tuple[Optional[str], str, str]:
    if tx["groupKey"] in groups:
        return tx["groupKey"], "exact", "Coincidencia exacta por TCG + nombre + edición + idioma + variante."
    for field, method, note in [
        ("baseKey", "flexible_ignore_foil", "Coincidencia flexible ignorando Foil/Non-foil."),
        ("looseKey", "flexible_ignore_language_variant", "Coincidencia flexible ignorando idioma y variante."),
        ("nameKey", "flexible_name_only", "Coincidencia flexible por TCG + nombre; revisar edición."),
    ]:
        candidates = indexes[field].get(tx[field], [])
        if candidates:
            chosen = choose_candidate(candidates, groups)
            if chosen:
                if len(candidates) > 1:
                    return chosen, method + "_multiple", note + " Había varias candidatas y se eligió la de mayor stock disponible."
                return chosen, method, note
    return None, "unmatched", "No se encontró compra compatible."


def aggregate_rows(cards: list[dict[str, Any]], key: str, value_key: str = "stockCost", limit: int = 12) -> list[dict[str, Any]]:
    totals = defaultdict(float)
    counts = defaultdict(float)
    rows_count = defaultdict(int)
    for card in cards:
        label = safe_text(card.get(key)) or "Sin dato"
        totals[label] += as_float(card.get(value_key))
        counts[label] += as_float(card.get("quantity"), 1)
        rows_count[label] += 1
    rows = [
        {"label": label, "total": round_money(total), "quantity": round_qty(counts[label]), "count": rows_count[label]}
        for label, total in totals.items()
    ]
    return sorted(rows, key=lambda item: item["total"], reverse=True)[:limit]


def unique_count(items: Iterable[Any]) -> int:
    return len({safe_text(item) for item in items if safe_text(item)})


def resolve_default_excel() -> Path:
    cwd = Path.cwd()
    candidates = []
    for name in DEFAULT_EXCEL_NAMES:
        candidates.extend([cwd / name, cwd.parent / name, Path(__file__).resolve().parents[1] / name, Path("/mnt/data") / name])
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return Path(DEFAULT_EXCEL_NAMES[-1])


def make_history_purchase_row(tx: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": tx["id"],
        "sourceRow": tx["sourceRow"],
        "date": tx["date"],
        "period": tx["period"],
        "year": tx["year"],
        "tcg": tx["tcg"],
        "cardName": tx["cardName"],
        "edition": tx["edition"],
        "language": tx["language"],
        "variant": tx["variant"],
        "quantity": tx["quantity"],
        "unitPurchaseValue": tx["unitPurchaseValue"],
        "totalPurchaseValue": tx["totalPurchaseValue"],
        "priceBand": tx["priceBand"],
        "operation": tx["operation"],
        "sellerBuyer": tx["sellerBuyer"],
        "orderNumber": tx["orderNumber"],
        "playsetConverted": tx["playsetConverted"],
    }


def finalize_group(group: dict[str, Any]) -> dict[str, Any]:
    purchased_qty = as_float(group["purchasedQuantity"])
    sold_qty = as_float(group["soldQuantity"])
    stock_qty = max(0.0, purchased_qty - sold_qty)
    gross = round_money(group["grossPurchaseValue"])
    avg = round_money(gross / purchased_qty) if purchased_qty > EPSILON else 0.0
    stock_cost = round_money(avg * stock_qty)
    group["purchasedQuantity"] = round_qty(purchased_qty)
    group["soldQuantity"] = round_qty(sold_qty)
    group["quantity"] = round_qty(stock_qty)
    group["grossPurchaseValue"] = gross
    group["saleRevenue"] = round_money(group["saleRevenue"])
    group["unitPurchaseValue"] = avg
    group["unitPrice"] = avg
    group["stockCost"] = stock_cost
    group["totalPurchaseValue"] = stock_cost
    group["total"] = stock_cost
    group["priceBand"] = price_band(avg)
    group["purchaseHistory"] = sorted(group["purchaseHistory"], key=lambda lot: (lot.get("date") or "9999", lot.get("sourceRow") or 0))
    group["stockLots"] = [
        {
            "sourceRow": lot["sourceRow"],
            "date": lot["date"],
            "period": lot["period"],
            "year": lot["year"],
            "quantity": round_qty(lot["remainingQuantity"]),
            "unitCost": lot["unitCost"],
            "totalCost": round_money(as_float(lot["remainingQuantity"]) * avg),
            "originalUnitCost": lot["unitCost"],
            "sellerBuyer": lot.get("sellerBuyer", ""),
            "orderNumber": lot.get("orderNumber", ""),
        }
        for lot in group["purchaseHistory"]
        if as_float(lot.get("remainingQuantity")) > EPSILON
    ]
    group["sourceRows"] = sorted(set(group["sourceRows"]))
    group["purchaseSourceRows"] = sorted(set(group["purchaseSourceRows"]))
    group["saleSourceRows"] = sorted(set(group["saleSourceRows"]))
    group["orderNumbers"] = sorted(set(group["orderNumbers"]))[:12]
    group["sellerBuyers"] = sorted(set(group["sellerBuyers"]))[:12]
    return group


def generate(excel_path: Path, output_dir: Path, min_unit_value: float, exclude_tcgs: str = "onepiece") -> dict[str, Any]:
    rows = read_sheet_rows(excel_path, "Colección")
    if not rows:
        raise RuntimeError("La hoja Colección no contiene filas.")

    header = [safe_text(value) for value in rows[0][1]]
    indexes = {name: idx for idx, name in enumerate(header) if name}
    required_columns = [
        "Order Number", "Mes", "Año", "Date", "Seller / Buyer", "Card Name", "Edition",
        "Playset", "Language", "Unit Price", "Quantity", "Total", "Tipo Operación", "TCG",
    ]
    missing = [column for column in required_columns if column not in indexes]
    if missing:
        raise RuntimeError("Faltan columnas requeridas en Colección: " + ", ".join(missing))

    excluded_tcg_set = parse_excluded_tcgs(exclude_tcgs)
    excluded_rows = []
    transactions = []
    invalid_rows = []
    operation_counter = Counter()
    playset_conversions = 0
    for row_index, row in rows[1:]:
        if not any(value not in (None, "") for value in row):
            continue
        tx = make_transaction(row_index, row, indexes)
        if is_excluded_material(tx, excluded_tcg_set):
            excluded_rows.append({"sourceRow": row_index, "cardName": tx.get("cardName"), "tcg": tx.get("tcg"), "reason": "TCG excluido temporalmente"})
            continue
        operation_counter[tx["operation"] or "Sin operación"] += 1
        if not tx["cardName"]:
            invalid_rows.append({"sourceRow": row_index, "reason": "Card Name vacío"})
            continue
        if tx["quantity"] <= 0:
            invalid_rows.append({"sourceRow": row_index, "cardName": tx["cardName"], "reason": "Quantity <= 0"})
            continue
        if tx["playsetConverted"]:
            playset_conversions += 1
        transactions.append(tx)

    groups: dict[str, dict[str, Any]] = {}
    sales: list[dict[str, Any]] = []
    purchase_transactions: list[dict[str, Any]] = []

    for tx in transactions:
        if tx["operationNormalized"] == "compra":
            purchase_transactions.append(tx)
            group = groups.setdefault(tx["groupKey"], create_group(tx))
            add_purchase(group, tx)
        elif tx["operationNormalized"] == "venta":
            sales.append(tx)

    indexes_by_key = build_indexes(groups)
    reconciliation = []
    matched_sales = 0
    unmatched_sales = 0
    overdrawn_sales = 0

    for sale in sorted(sales, key=lambda tx: (tx.get("date") or "", tx.get("sourceRow") or 0)):
        group_key, method, note = match_sale(sale, groups, indexes_by_key)
        if group_key is None:
            unmatched_sales += 1
            reconciliation.append({
                "sourceRow": sale["sourceRow"],
                "cardName": sale["cardName"],
                "edition": sale["edition"],
                "tcg": sale["tcg"],
                "language": sale["language"],
                "quantity": sale["quantity"],
                "saleValue": sale["saleValue"],
                "status": "unmatched",
                "method": method,
                "note": note,
            })
            continue
        group = groups[group_key]
        before_available = available_stock(group)
        sale_entry = add_sale(group, sale, method)
        matched_sales += 1
        status = "matched"
        if before_available + EPSILON < as_float(sale["quantity"]):
            status = "overdrawn"
            overdrawn_sales += 1
        if method != "exact" or status != "matched":
            reconciliation.append({
                "sourceRow": sale["sourceRow"],
                "cardName": sale["cardName"],
                "edition": sale["edition"],
                "tcg": sale["tcg"],
                "language": sale["language"],
                "quantity": sale["quantity"],
                "saleValue": sale["saleValue"],
                "matchedGroupId": group["id"],
                "matchedName": group["cardName"],
                "matchedEdition": group["edition"],
                "matchedLanguage": group["language"],
                "status": status,
                "method": method,
                "matchedQuantity": sale_entry["matchedQuantity"],
                "note": note,
            })

    finalized_groups = [finalize_group(group) for group in groups.values()]
    current_stock = [group for group in finalized_groups if as_float(group["quantity"]) > EPSILON]
    visible_cards = [group for group in current_stock if as_float(group["unitPurchaseValue"]) + EPSILON >= min_unit_value]
    hidden_below_threshold = [group for group in current_stock if as_float(group["unitPurchaseValue"]) + EPSILON < min_unit_value]
    sold_out_groups = [group for group in finalized_groups if as_float(group["quantity"]) <= EPSILON]

    visible_cards.sort(key=lambda card: (as_float(card["stockCost"]), as_float(card["unitPurchaseValue"]), safe_text(card["cardName"])), reverse=True)

    historical_rows = [make_history_purchase_row(tx) for tx in purchase_transactions]
    stock_lots_rows = []
    for card in visible_cards:
        for lot in card.get("stockLots", []):
            stock_lots_rows.append({
                "id": card["id"],
                "sourceRow": lot["sourceRow"],
                "date": lot["date"],
                "period": lot["period"],
                "year": lot["year"],
                "tcg": card["tcg"],
                "cardName": card["cardName"],
                "edition": card["edition"],
                "language": card["language"],
                "variant": card["variant"],
                "quantity": lot["quantity"],
                "unitPurchaseValue": card["unitPurchaseValue"],
                "totalPurchaseValue": lot["totalCost"],
                "priceBand": card["priceBand"],
                "operation": "Stock actual",
            })

    total_current_cost = round_money(sum(as_float(card["stockCost"]) for card in visible_cards))
    total_current_units = round_qty(sum(as_float(card["quantity"]) for card in visible_cards))
    gross_purchase_value = round_money(sum(as_float(group["grossPurchaseValue"]) for group in finalized_groups))
    total_sale_revenue = round_money(sum(as_float(group["saleRevenue"]) for group in finalized_groups))
    avg_unit_value = round_money(total_current_cost / total_current_units) if total_current_units > EPSILON else 0

    metadata = {
        "generatedAt": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "sourceFile": excel_path.name,
        "sourceSheet": "Colección",
        "displayRule": f"Stock actual agrupado con coste unitario medio >= {min_unit_value:.2f} EUR",
        "minUnitPurchaseValue": round_money(min_unit_value),
        "thresholdMode": "average_unit_cost_after_grouping_and_sales",
        "totalSourceRows": len(transactions),
        "purchaseRows": len(purchase_transactions),
        "saleRows": len(sales),
        "matchedSaleRows": matched_sales,
        "unmatchedSaleRows": unmatched_sales,
        "overdrawnSaleRows": overdrawn_sales,
        "invalidRows": len(invalid_rows),
        "excludedRows": len(excluded_rows),
        "excludedTcgs": sorted(excluded_tcg_set),
        "playsetConversions": playset_conversions,
        "purchaseGroups": len(groups),
        "currentStockGroups": len(current_stock),
        "visibleRows": len(visible_cards),
        "hiddenCurrentStockBelowThreshold": len(hidden_below_threshold),
        "soldOutGroupsRemoved": len(sold_out_groups),
        "visibleTotalPurchaseValue": total_current_cost,
        "visibleTotalQuantity": total_current_units,
        "visibleAverageUnitPurchaseValue": avg_unit_value,
        "grossPurchaseValue": gross_purchase_value,
        "totalSaleRevenue": total_sale_revenue,
        "operationBreakdown": dict(operation_counter),
        "groupingKey": "TCG + nombre normalizado + edición normalizada + idioma + variante simplificada Foil/Non-foil",
        "persistenceStrategy": "localStorage + exportable JSON files",
    }

    review = [item for item in reconciliation if item.get("status") != "matched" or not item.get("method", "").startswith("exact")]

    payload: dict[str, Any] = {
        "metadata": metadata,
        "cards": visible_cards,
        "transactions": historical_rows,
        "stockLots": stock_lots_rows,
        "review": review[:500],
        "invalidRows": invalid_rows[:200],
        "excludedRows": excluded_rows[:500],
        "aggregates": {
            "topEditionsByPurchase": aggregate_rows(visible_cards, "edition"),
            "topCardsByPurchase": aggregate_rows(visible_cards, "cardName"),
            "byTcg": aggregate_rows(visible_cards, "tcg", limit=20),
            "byLanguage": aggregate_rows(visible_cards, "language", limit=20),
            "byPriceBand": aggregate_rows(visible_cards, "priceBand", limit=20),
        },
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "portfolio-data.json"
    js_path = output_dir / "portfolio-data.js"
    json_text = json.dumps(payload, ensure_ascii=False, indent=2)
    json_path.write_text(json_text + "\n", encoding="utf-8")
    js_path.write_text("window.portfolioData = " + json_text + ";\n", encoding="utf-8")

    report_json = output_dir / "stock-reconciliation-report.json"
    report_json.write_text(json.dumps(reconciliation, ensure_ascii=False, indent=2), encoding="utf-8")
    report_csv = output_dir / "stock-reconciliation-report.csv"
    with report_csv.open("w", encoding="utf-8", newline="") as handle:
        fieldnames = [
            "sourceRow", "cardName", "edition", "tcg", "language", "quantity", "saleValue", "status", "method",
            "matchedGroupId", "matchedName", "matchedEdition", "matchedLanguage", "matchedQuantity", "note",
        ]
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(reconciliation)

    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Genera portfolio-data de stock actual para GitHub Pages.")
    parser.add_argument("--excel", type=Path, default=resolve_default_excel(), help="Ruta del Excel fuente.")
    parser.add_argument("--out", type=Path, default=Path("docs/data"), help="Directorio de salida para JSON/JS.")
    parser.add_argument("--min-unit", type=float, default=10.0, help="Coste unitario medio minimo en EUR.")
    parser.add_argument("--exclude-tcgs", default="onepiece", help="TCGs separados por coma a excluir temporalmente del JSON generado. Por defecto: onepiece")
    args = parser.parse_args()

    payload = generate(args.excel, args.out, args.min_unit, args.exclude_tcgs)
    meta = payload["metadata"]
    print("Dataset de stock actual generado")
    print(f"  Fuente: {args.excel}")
    print(f"  Regla: {meta['displayRule']}")
    print(f"  Filas fuente: {meta['totalSourceRows']}")
    print(f"  Grupos con stock actual: {meta['currentStockGroups']}")
    print(f"  Elementos visibles: {meta['visibleRows']}")
    print(f"  Filas excluidas temporalmente: {meta.get('excludedRows', 0)}")
    print(f"  Grupos vendidos eliminados: {meta['soldOutGroupsRemoved']}")
    print(f"  Ventas sin match: {meta['unmatchedSaleRows']}")
    print(f"  Salida: {args.out / 'portfolio-data.json'}")
    print(f"  Salida: {args.out / 'portfolio-data.js'}")


if __name__ == "__main__":
    main()
