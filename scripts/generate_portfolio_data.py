#!/usr/bin/env python3
"""Generate the static portfolio dataset from the Excel collection.

The web intentionally receives a reduced dataset: only purchase rows whose
unit purchase value is equal to or greater than the configured threshold.
The Excel remains the complete source of truth.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import zipfile
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
import xml.etree.ElementTree as ET
from urllib.parse import quote

NS = {"main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
EXCEL_EPOCH = datetime(1899, 12, 30)
DEFAULT_EXCEL_NAMES = ["MI COLECCION TCGS.xlsx", "MI COLECCIÓN TCGS.xlsx"]


def col_to_idx(cell_ref: str) -> int:
    match = re.match(r"([A-Z]+)", cell_ref)
    if not match:
        return 0
    idx = 0
    for char in match.group(1):
        idx = idx * 26 + ord(char) - 64
    return idx - 1


def safe_text(value) -> str:
    if value is None:
        return ""
    return str(value).strip()


def as_float(value, default: float = 0.0) -> float:
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
    return round(float(value or 0), 4)


def excel_date_to_iso(value):
    if value in (None, ""):
        return ""
    if isinstance(value, (int, float)):
        dt = EXCEL_EPOCH + timedelta(days=float(value))
        if dt.time().hour == 0 and dt.time().minute == 0 and dt.time().second == 0:
            return dt.date().isoformat()
        return dt.replace(microsecond=0).isoformat()
    return str(value)


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


def cell_value(cell, shared_strings: list[str]):
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


def read_sheet_rows(excel_path: Path, sheet_name: str) -> list[tuple[int, list]]:
    with zipfile.ZipFile(excel_path) as zip_file:
        shared = load_shared_strings(zip_file)
        xml_path = sheet_path(zip_file, sheet_name)
        root = ET.fromstring(zip_file.read(xml_path))
        rows = []
        for row in root.findall(".//main:sheetData/main:row", NS):
            row_index = int(row.attrib["r"])
            values = []
            for cell in row.findall("main:c", NS):
                idx = col_to_idx(cell.attrib.get("r", "A1"))
                while len(values) <= idx:
                    values.append(None)
                values[idx] = cell_value(cell, shared)
            rows.append((row_index, values))
        return rows


def clean_scryfall_name(card_name: str) -> str:
    name = safe_text(card_name)
    name = re.sub(r"\s*\[Playset\]\s*", "", name, flags=re.I)
    name = re.sub(r"\s*\(V\.\d+[^)]*\)\s*", "", name, flags=re.I)
    name = re.sub(r"\s+", " ", name).strip()
    return name


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
    return "20€ - 49,99€"


def make_card(row_index: int, row: list, indexes: dict[str, int]) -> dict:
    def get(column: str):
        idx = indexes[column]
        return row[idx] if idx < len(row) else None

    unit_value = round_money(as_float(get("Unit Price")))
    quantity = as_float(get("Quantity"))
    total_value = round_money(as_float(get("Total")))
    card_name = safe_text(get("Card Name"))
    edition = safe_text(get("Edition"))
    language = safe_text(get("Language")) or "Sin idioma"
    operation = safe_text(get("Tipo Operación"))
    tcg = safe_text(get("TCG")) or "Sin TCG"
    order_number = safe_text(get("Order Number"))
    date_iso = excel_date_to_iso(get("Date"))
    seller_buyer = safe_text(get("Seller / Buyer"))
    playset = safe_text(get("Playset"))
    sale_value = round_money(as_float(get("Precio de venta"))) if "Precio de venta" in indexes else 0
    base_name = clean_scryfall_name(card_name)
    scryfall_uri = build_scryfall_search_uri(card_name, tcg)

    return {
        "id": f"excel-row-{row_index}",
        "sourceRow": row_index,
        "orderNumber": order_number,
        "month": safe_text(get("Mes")),
        "year": int(as_float(get("Año"))) if get("Año") not in (None, "") else None,
        "date": date_iso,
        "sellerBuyer": seller_buyer,
        "name": card_name,
        "cardName": card_name,
        "scryfallName": base_name,
        "edition": edition,
        "playset": playset,
        "language": language,
        "unitPurchaseValue": unit_value,
        "unitPrice": unit_value,
        "quantity": quantity,
        "totalPurchaseValue": total_value,
        "total": total_value,
        "operation": operation,
        "saleValue": sale_value,
        "tcg": tcg,
        "priceBand": price_band(unit_value),
        "images": {
            "small": "",
            "normal": "",
            "large": "",
            "artCrop": "",
            "status": "pending" if scryfall_uri else "not_applicable",
        },
        "scryfall": {
            "searchUri": scryfall_uri,
            "resolved": False,
        },
    }


def aggregate(cards: list[dict], key: str, value_key: str = "totalPurchaseValue", limit: int = 12) -> list[dict]:
    totals = defaultdict(float)
    counts = defaultdict(float)
    for card in cards:
        label = safe_text(card.get(key)) or "Sin dato"
        totals[label] += as_float(card.get(value_key))
        counts[label] += as_float(card.get("quantity"), 1)
    rows = [
        {"label": label, "total": round_money(total), "quantity": round_money(counts[label])}
        for label, total in totals.items()
    ]
    return sorted(rows, key=lambda item: item["total"], reverse=True)[:limit]


def resolve_default_excel() -> Path:
    cwd = Path.cwd()
    candidates = []
    for name in DEFAULT_EXCEL_NAMES:
        candidates.extend([cwd / name, cwd.parent / name, Path(__file__).resolve().parents[1] / name])
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return Path(DEFAULT_EXCEL_NAMES[-1])


def generate(excel_path: Path, output_dir: Path, min_unit_value: float) -> dict:
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

    source_rows = []
    visible_cards = []
    invalid_rows = []
    operation_counter = Counter()

    for row_index, row in rows[1:]:
        if not any(value not in (None, "") for value in row):
            continue
        operation = safe_text(row[indexes["Tipo Operación"]] if indexes["Tipo Operación"] < len(row) else "")
        operation_counter[operation or "Sin operacion"] += 1
        unit_value = as_float(row[indexes["Unit Price"]] if indexes["Unit Price"] < len(row) else None)
        name = safe_text(row[indexes["Card Name"]] if indexes["Card Name"] < len(row) else "")
        source_rows.append((row_index, row, operation, unit_value, name))

        if not name:
            invalid_rows.append({"sourceRow": row_index, "reason": "Card Name vacio"})
            continue
        if operation.lower() != "compra":
            continue
        if unit_value < min_unit_value:
            continue
        visible_cards.append(make_card(row_index, row, indexes))

    visible_cards.sort(key=lambda card: (card["unitPurchaseValue"], card["totalPurchaseValue"]), reverse=True)

    purchase_rows = sum(1 for _, _, operation, _, _ in source_rows if operation.lower() == "compra")
    below_threshold = sum(
        1 for _, _, operation, unit_value, name in source_rows
        if operation.lower() == "compra" and name and unit_value < min_unit_value
    )
    non_purchase_rows = sum(1 for _, _, operation, _, _ in source_rows if operation.lower() != "compra")
    total_visible_value = round_money(sum(as_float(card["totalPurchaseValue"]) for card in visible_cards))
    total_visible_units = round_money(sum(as_float(card["quantity"]) for card in visible_cards))
    avg_unit_value = round_money(
        sum(as_float(card["unitPurchaseValue"]) for card in visible_cards) / len(visible_cards)
    ) if visible_cards else 0

    review = []
    for card in visible_cards:
        reasons = []
        if not card["edition"]:
            reasons.append("Edicion vacia")
        if not card["language"] or card["language"] == "Sin idioma":
            reasons.append("Idioma vacio")
        if "magic" in card["tcg"].lower() and not card["scryfall"]["resolved"]:
            # Summary only; not every card needs to be listed as an error.
            pass
        if reasons:
            review.append({
                "id": card["id"],
                "cardName": card["cardName"],
                "edition": card["edition"],
                "language": card["language"],
                "reason": "; ".join(reasons),
                "sourceRow": card["sourceRow"],
            })

    metadata = {
        "generatedAt": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "sourceFile": excel_path.name,
        "sourceSheet": "Colección",
        "displayRule": f"Tipo Operacion = Compra y Unit Price >= {min_unit_value:.2f} EUR",
        "minUnitPurchaseValue": round_money(min_unit_value),
        "thresholdMode": "unit_purchase_value",
        "totalSourceRows": len(source_rows),
        "purchaseRows": purchase_rows,
        "visibleRows": len(visible_cards),
        "excludedPurchaseRowsBelowThreshold": below_threshold,
        "excludedNonPurchaseRows": non_purchase_rows,
        "invalidRows": len(invalid_rows),
        "visibleTotalPurchaseValue": total_visible_value,
        "visibleTotalQuantity": total_visible_units,
        "visibleAverageUnitPurchaseValue": avg_unit_value,
        "operationBreakdown": dict(operation_counter),
        "imageResolution": {
            "magicRowsPendingScryfall": sum(1 for card in visible_cards if "magic" in card["tcg"].lower() and not card["scryfall"]["resolved"]),
            "nonMagicRowsWithoutScryfall": sum(1 for card in visible_cards if "magic" not in card["tcg"].lower()),
        },
    }

    payload = {
        "metadata": metadata,
        "cards": visible_cards,
        "review": review,
        "invalidRows": invalid_rows[:200],
        "aggregates": {
            "topEditionsByPurchase": aggregate(visible_cards, "edition"),
            "topCardsByPurchase": aggregate(visible_cards, "cardName"),
            "byTcg": aggregate(visible_cards, "tcg", limit=20),
            "byLanguage": aggregate(visible_cards, "language", limit=20),
            "byPriceBand": aggregate(visible_cards, "priceBand", limit=20),
        },
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "portfolio-data.json"
    js_path = output_dir / "portfolio-data.js"
    json_text = json.dumps(payload, ensure_ascii=False, indent=2)
    json_path.write_text(json_text + "\n", encoding="utf-8")
    js_path.write_text("window.portfolioData = " + json_text + ";\n", encoding="utf-8")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Genera portfolio-data filtrado para GitHub Pages.")
    parser.add_argument("--excel", type=Path, default=resolve_default_excel(), help="Ruta del Excel fuente.")
    parser.add_argument("--out", type=Path, default=Path("docs/data"), help="Directorio de salida para JSON/JS.")
    parser.add_argument("--min-unit", type=float, default=20.0, help="Valor minimo de compra por unidad en EUR.")
    args = parser.parse_args()

    payload = generate(args.excel, args.out, args.min_unit)
    meta = payload["metadata"]
    print("Dataset generado")
    print(f"  Fuente: {args.excel}")
    print(f"  Regla: {meta['displayRule']}")
    print(f"  Filas fuente: {meta['totalSourceRows']}")
    print(f"  Compras visibles: {meta['visibleRows']}")
    print(f"  Compras ocultas por umbral: {meta['excludedPurchaseRowsBelowThreshold']}")
    print(f"  Salida: {args.out / 'portfolio-data.json'}")
    print(f"  Salida: {args.out / 'portfolio-data.js'}")


if __name__ == "__main__":
    main()
