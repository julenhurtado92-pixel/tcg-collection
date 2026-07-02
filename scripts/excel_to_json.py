#!/usr/bin/env python3
"""Convert the collection Excel into a normalized JSON file.

This implementation intentionally avoids heavyweight Excel dependencies. It reads
.xlsx files directly as zipped XML, which is enough for this collection tracker
and makes the script easier to run in restricted environments.
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
import unicodedata
import zipfile
from collections import Counter
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Tuple
import xml.etree.ElementTree as ET

NS_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
NS_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"

COLUMN_ALIASES: Dict[str, List[str]] = {
    "orderNumber": ["order number", "pedido", "numero pedido", "n pedido", "order"],
    "month": ["mes", "month"],
    "year": ["ano", "año", "year"],
    "date": ["date", "fecha"],
    "sellerBuyer": ["seller buyer", "seller / buyer", "seller", "buyer", "vendedor", "comprador"],
    "cardName": ["card name", "card", "name", "nombre", "nombre carta", "nombre de carta", "carta", "card_name", "cardname"],
    "edition": ["edition", "edicion", "expansion", "coleccion", "set", "set name", "edition name", "nombre edicion", "nombre expansion", "edicion coleccion"],
    "playset": ["playset", "play set"],
    "setCode": ["set code", "edition code", "codigo set", "codigo edicion", "codigo expansion", "code", "setcode"],
    "collectorNumber": ["collector number", "number", "numero", "num", "numero coleccion", "card number", "n carta", "numero carta", "collector_number"],
    "language": ["language", "lang", "idioma", "lenguaje"],
    "condition": ["condition", "condicion", "estado carta", "estado de carta", "quality", "calidad"],
    "quantity": ["quantity", "qty", "cantidad", "unidades", "copias", "numero copias"],
    "buyPrice": ["unit price", "buy price", "precio compra", "precio unitario", "coste unitario", "precio carta", "precio", "importe unidad", "coste carta"],
    "totalBuyPrice": ["total", "total buy price", "precio total", "coste total", "importe total", "gasto", "total compra"],
    "operationType": ["tipo operacion", "tipo operación", "operation", "operation type", "operacion", "operación", "movimiento", "tipo movimiento", "compra venta", "tipo"],
    "salePrice": ["precio de venta", "sale price", "precio venta"],
    "status": ["status", "estado operacion", "estado operación", "situacion", "situación", "estado pedido", "estado compra"],
    "foiling": ["foil", "foiling", "finish", "finishing", "acabado", "version", "variant", "variante"],
    "tcg": ["tcg", "game", "juego"],
    "cardmarketUrl": ["cardmarket", "cardmarket url", "url cardmarket", "cm url", "link cardmarket"],
    "scryfallId": ["scryfall", "scryfall id", "id scryfall"],
    "scryfallUrl": ["scryfall url", "url scryfall", "link scryfall"],
    "notes": ["notes", "notas", "comentario", "comentarios", "observaciones"],
}

DEFAULTS = {
    "language": "ES",
    "condition": "EX",
    "quantity": 1,
    "status": "Holding",
}

STATUS_KEYWORDS = {
    "cancel": "Cancelado",
    "cancelado": "Cancelado",
    "cancelada": "Cancelado",
    "sold": "Sold",
    "venta": "Sold",
    "vendido": "Sold",
    "vendida": "Sold",
    "sell": "Sold",
    "watch": "Watchlist",
    "seguimiento": "Watchlist",
    "wishlist": "Watchlist",
    "compra": "Holding",
    "buy": "Holding",
    "holding": "Holding",
}

LANG_NORMALIZATION = {
    "ingles": "Inglés",
    "inglés": "Inglés",
    "english": "Inglés",
    "espanol": "Español",
    "español": "Español",
    "spanish": "Español",
    "japones": "Japonés",
    "japonés": "Japonés",
    "japanese": "Japonés",
    "aleman": "Alemán",
    "alemán": "Alemán",
    "german": "Alemán",
    "frances": "Francés",
    "francés": "Francés",
    "french": "Francés",
    "italiano": "Italiano",
    "italian": "Italiano",
    "ruso": "Ruso",
    "russian": "Ruso",
    "chino s": "Chino-S",
    "chino t": "Chino-T",
}


def normalize_header(value: Any) -> str:
    text = "" if value is None else str(value)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def normalize_key(value: Any) -> str:
    return normalize_header(value).replace(" ", "")


ALIAS_TO_FIELD: Dict[str, str] = {}
for field, aliases in COLUMN_ALIASES.items():
    for alias in aliases:
        ALIAS_TO_FIELD[normalize_key(alias)] = field


def find_excel(path_arg: Optional[str], base_dir: Path) -> Path:
    if path_arg:
        path = Path(path_arg)
        if not path.is_absolute():
            path = base_dir / path
        if not path.exists():
            raise FileNotFoundError(f"Excel file not found: {path}")
        return path
    candidates = [p for p in base_dir.glob("*.xlsx") if not p.name.startswith("~$")]
    if not candidates:
        raise FileNotFoundError("No .xlsx file found. Pass --excel path/to/file.xlsx")
    preferred = [p for p in candidates if "coleccion" in normalize_header(p.stem) or "collection" in normalize_header(p.stem)]
    return sorted(preferred or candidates, key=lambda p: p.name.lower())[0]


def read_workbook_sheets(zf: zipfile.ZipFile) -> List[Tuple[str, str]]:
    wb = ET.fromstring(zf.read("xl/workbook.xml"))
    rels = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
    rel_map = {rel.attrib["Id"]: rel.attrib["Target"] for rel in rels}
    sheets: List[Tuple[str, str]] = []
    for sheet in wb.findall(f".//{{{NS_MAIN}}}sheet"):
        name = sheet.attrib.get("name", "")
        rid = sheet.attrib.get(f"{{{NS_REL}}}id")
        target = rel_map.get(rid or "", "")
        if not target:
            continue
        target = target.lstrip("/")
        if not target.startswith("xl/"):
            target = "xl/" + target
        sheets.append((name, target))
    return sheets


def read_shared_strings(zf: zipfile.ZipFile) -> List[str]:
    if "xl/sharedStrings.xml" not in zf.namelist():
        return []
    xml = zf.read("xl/sharedStrings.xml").decode("utf-8")
    shared: List[str] = []
    for item in re.finditer(r"<si(?:\s[^>]*)?>(.*?)</si>", xml, re.S):
        texts = re.findall(r"<t[^>]*>(.*?)</t>", item.group(1), re.S)
        shared.append(html.unescape("".join(texts)))
    return shared


def col_to_idx(cell_ref: str) -> int:
    match = re.match(r"([A-Z]+)", cell_ref or "")
    if not match:
        return 0
    result = 0
    for char in match.group(1):
        result = result * 26 + ord(char) - 64
    return result - 1


def parse_scalar(raw: str) -> Any:
    if raw is None:
        return None
    if re.fullmatch(r"-?\d+", raw):
        try:
            return int(raw)
        except Exception:
            return raw
    if re.fullmatch(r"-?(?:\d+\.\d+|\d+\.|\.\d+)(?:[Ee][+-]?\d+)?", raw) or re.fullmatch(r"-?\d+[Ee][+-]?\d+", raw):
        try:
            return float(raw)
        except Exception:
            return raw
    return raw


def cell_value(attrs: str, body: str, shared: List[str]) -> Any:
    type_match = re.search(r't="([^"]+)"', attrs)
    cell_type = type_match.group(1) if type_match else None
    if cell_type == "inlineStr":
        return html.unescape("".join(re.findall(r"<t[^>]*>(.*?)</t>", body, re.S)))
    value_match = re.search(r"<v>(.*?)</v>", body, re.S)
    if not value_match:
        return None
    raw = html.unescape(value_match.group(1))
    if cell_type == "s":
        try:
            return shared[int(raw)]
        except Exception:
            return raw
    if cell_type == "b":
        return raw == "1"
    return parse_scalar(raw)


def iter_sheet_rows(zf: zipfile.ZipFile, sheet_path: str, shared: List[str]) -> Iterator[Tuple[int, List[Any]]]:
    xml = zf.read(sheet_path).decode("utf-8")
    for row_match in re.finditer(r'<row[^>]*\sr="(\d+)"[^>]*>(.*?)</row>', xml, re.S):
        row_number = int(row_match.group(1))
        values: List[Any] = []
        for cell_match in re.finditer(r"<c\s([^>]*)>(.*?)</c>", row_match.group(2), re.S):
            attrs, body = cell_match.group(1), cell_match.group(2)
            ref_match = re.search(r'r="([A-Z]+\d+)"', attrs)
            if not ref_match:
                continue
            col_idx = col_to_idx(ref_match.group(1))
            while len(values) <= col_idx:
                values.append(None)
            values[col_idx] = cell_value(attrs, body, shared)
        yield row_number, values


def to_jsonable(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (int, float, bool)):
        return value
    text = str(value).strip()
    return text if text != "" else None


def excel_serial_to_iso(value: Any) -> Optional[str]:
    number = parse_number(value)
    if number is None:
        return to_jsonable(value)
    if not 1 <= number <= 100000:
        return to_jsonable(value)
    dt = datetime(1899, 12, 30) + timedelta(days=number)
    if abs(number - int(number)) < 1e-9:
        return dt.date().isoformat()
    return dt.isoformat(timespec="seconds")


def parse_number(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return None
    text = text.replace("EUR", "").replace("eur", "").replace("euro", "").replace("euros", "")
    text = text.replace("$", "").replace("GBP", "").replace("gbp", "")
    text = text.replace("\xa0", " ").replace(" ", "")
    text = re.sub(r"[^0-9,\.\-]", "", text)
    if not text or text in {"-", ".", ","}:
        return None
    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        text = text.replace(",", ".")
    try:
        return float(Decimal(text))
    except (InvalidOperation, ValueError):
        return None


def parse_int(value: Any, default: int = 1) -> int:
    number = parse_number(value)
    if number is None:
        return default
    try:
        return max(0, int(round(number)))
    except Exception:
        return default


def clean_lookup_name(value: Any) -> Optional[str]:
    text = to_jsonable(value)
    if text is None:
        return None
    text = str(text).strip()
    # Cardmarket exports often annotate grouped rows as "[Playset]".
    text = re.sub(r"\s*\[(?:playset|set|lot)\]\s*$", "", text, flags=re.I)
    return text.strip() or None


def normalize_language(value: Any) -> str:
    text = to_jsonable(value)
    if not text:
        return DEFAULTS["language"]
    norm = normalize_header(text)
    return LANG_NORMALIZATION.get(norm, str(text).strip())


def infer_status(explicit_status: Any, operation: Any) -> str:
    for value in (explicit_status, operation):
        text = normalize_header(value)
        if not text:
            continue
        for keyword, status in STATUS_KEYWORDS.items():
            if keyword in text:
                return status
    return DEFAULTS["status"]


def score_header(values: List[Any]) -> Tuple[int, Dict[str, int]]:
    mapping: Dict[str, int] = {}
    score = 0
    for idx, value in enumerate(values):
        key = normalize_key(value)
        if not key:
            continue
        field = ALIAS_TO_FIELD.get(key)
        if field and field not in mapping:
            mapping[field] = idx
            score += 1
    if "cardName" in mapping:
        score += 4
    if "edition" in mapping or "setCode" in mapping:
        score += 2
    if "quantity" in mapping:
        score += 1
    return score, mapping


def build_raw_header_map(headers: List[Any]) -> Dict[int, str]:
    result: Dict[int, str] = {}
    used: Dict[str, int] = {}
    for idx, value in enumerate(headers):
        name = str(value).strip() if value is not None else f"col_{idx+1}"
        if not name:
            name = f"col_{idx+1}"
        count = used.get(name, 0)
        used[name] = count + 1
        result[idx] = name if count == 0 else f"{name}_{count+1}"
    return result


def choose_sheet_and_header(zf: zipfile.ZipFile, requested_sheet: Optional[str]) -> Tuple[str, str, int, List[Any], Dict[str, int]]:
    shared = read_shared_strings(zf)
    sheets = read_workbook_sheets(zf)
    selected = []
    if requested_sheet:
        wanted = normalize_header(requested_sheet)
        selected = [(name, path) for name, path in sheets if normalize_header(name) == wanted]
        if not selected:
            raise ValueError(f"Sheet '{requested_sheet}' not found. Available: {', '.join(name for name, _ in sheets)}")
    else:
        selected = sheets
    best: Optional[Tuple[int, str, str, int, List[Any], Dict[str, int]]] = None
    for sheet_name, sheet_path in selected:
        for row_number, values in iter_sheet_rows(zf, sheet_path, shared):
            if row_number > 40:
                break
            score, mapping = score_header(values)
            if best is None or score > best[0]:
                best = (score, sheet_name, sheet_path, row_number, values, mapping)
    if not best or best[0] < 5 or "cardName" not in best[5]:
        raise ValueError("Could not detect a collection header row. Run --inspect to see headers.")
    _, sheet_name, sheet_path, row_number, values, mapping = best
    return sheet_name, sheet_path, row_number, values, mapping


def extract_cards(zf: zipfile.ZipFile, sheet_name: str, sheet_path: str, header_row: int, headers: List[Any], mapping: Dict[str, int]) -> List[Dict[str, Any]]:
    shared = read_shared_strings(zf)
    raw_header_map = build_raw_header_map(headers)
    cards: List[Dict[str, Any]] = []

    def value_from(values: List[Any], field: str) -> Any:
        idx = mapping.get(field)
        if idx is None or idx >= len(values):
            return None
        return values[idx]

    for row_number, values in iter_sheet_rows(zf, sheet_path, shared):
        if row_number <= header_row:
            continue
        if all(value is None or str(value).strip() == "" for value in values):
            continue
        card_name = to_jsonable(value_from(values, "cardName"))
        if not card_name:
            continue
        quantity = parse_int(value_from(values, "quantity"), int(DEFAULTS["quantity"]))
        buy_price = parse_number(value_from(values, "buyPrice"))
        total_buy = parse_number(value_from(values, "totalBuyPrice"))
        if buy_price is None and total_buy is not None and quantity:
            buy_price = round(total_buy / quantity, 4)
        if total_buy is None and buy_price is not None:
            total_buy = round(buy_price * quantity, 4)
        operation = to_jsonable(value_from(values, "operationType"))
        status = infer_status(value_from(values, "status"), operation)
        raw_values = {
            raw_header_map[idx]: to_jsonable(value)
            for idx, value in enumerate(values)
            if idx in raw_header_map and to_jsonable(value) is not None
        }
        card = {
            "internalId": f"mtg-row-{row_number:05d}",
            "source": {"sheet": sheet_name, "row": row_number},
            "orderNumber": to_jsonable(value_from(values, "orderNumber")),
            "date": excel_serial_to_iso(value_from(values, "date")),
            "sellerBuyer": to_jsonable(value_from(values, "sellerBuyer")),
            "cardName": str(card_name).strip(),
            "lookupName": clean_lookup_name(card_name),
            "edition": to_jsonable(value_from(values, "edition")),
            "setCode": to_jsonable(value_from(values, "setCode")),
            "collectorNumber": to_jsonable(value_from(values, "collectorNumber")),
            "playset": to_jsonable(value_from(values, "playset")),
            "language": normalize_language(value_from(values, "language")),
            "condition": str(to_jsonable(value_from(values, "condition")) or DEFAULTS["condition"]).strip(),
            "quantity": quantity,
            "buyPrice": buy_price,
            "totalBuyPrice": total_buy,
            "salePrice": parse_number(value_from(values, "salePrice")),
            "operationType": operation,
            "status": status,
            "foiling": to_jsonable(value_from(values, "foiling")),
            "tcg": to_jsonable(value_from(values, "tcg")),
            "cardmarketUrl": to_jsonable(value_from(values, "cardmarketUrl")),
            "scryfallId": to_jsonable(value_from(values, "scryfallId")),
            "scryfallUrl": to_jsonable(value_from(values, "scryfallUrl")),
            "notes": to_jsonable(value_from(values, "notes")),
            "raw": raw_values,
        }
        cards.append(card)
    return cards


def inspect_workbook(path: Path) -> None:
    with zipfile.ZipFile(path) as zf:
        shared = read_shared_strings(zf)
        print(f"Workbook: {path}")
        for sheet_name, sheet_path in read_workbook_sheets(zf):
            print(f"\nSheet: {sheet_name} ({sheet_path})")
            for row_number, values in iter_sheet_rows(zf, sheet_path, shared):
                if row_number > 10:
                    break
                if any(value is not None and str(value).strip() for value in values):
                    score, mapping = score_header(values)
                    preview = " | ".join(str(v) if v is not None else "" for v in values[:20])
                    print(f"  row {row_number:02d} score={score} mapping={mapping}")
                    print(f"    {preview}")


def write_output(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Convert collection Excel to normalized JSON")
    parser.add_argument("--excel", help="Path to the workbook. Defaults to the first .xlsx in the repo root.")
    parser.add_argument("--sheet", default="Colección", help="Worksheet name to read. Default: Colección")
    parser.add_argument("--out", default="data/collection.raw.json", help="Output JSON path")
    parser.add_argument("--base-dir", default=".", help="Repository root")
    parser.add_argument("--inspect", action="store_true", help="Inspect workbook sheets and likely headers")
    args = parser.parse_args()

    base_dir = Path(args.base_dir).resolve()
    excel_path = find_excel(args.excel, base_dir)
    if args.inspect:
        inspect_workbook(excel_path)
        return 0

    with zipfile.ZipFile(excel_path) as zf:
        sheet_name, sheet_path, header_row, headers, mapping = choose_sheet_and_header(zf, args.sheet)
        cards = extract_cards(zf, sheet_name, sheet_path, header_row, headers, mapping)

    out_path = Path(args.out)
    if not out_path.is_absolute():
        out_path = base_dir / out_path
    operations = Counter(str(card.get("operationType") or "") for card in cards)
    languages = Counter(str(card.get("language") or "") for card in cards)
    payload = {
        "generatedAt": datetime.now().astimezone().isoformat(timespec="seconds"),
        "source": {
            "type": "excel",
            "file": excel_path.name,
            "sheet": sheet_name,
            "headerRow": header_row,
            "mappedColumns": mapping,
        },
        "stats": {
            "rows": len(cards),
            "operations": dict(operations),
            "languages": dict(languages),
        },
        "cards": cards,
    }
    write_output(out_path, payload)
    print(f"Wrote {out_path} with {len(cards)} rows from sheet '{sheet_name}'")
    print(f"Operations: {dict(operations)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
