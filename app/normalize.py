"""Normalisation + validation of extracted purchase data. Independent of which extractor produced it."""
import re, calendar
from datetime import date, datetime

MONTHS = {m.lower(): i for i, m in enumerate(calendar.month_abbr) if m}

def num(v):
    if v is None or v == "": return None
    if isinstance(v, (int, float)): return float(v)
    s = re.sub(r"[^\d.\-]", "", str(v).replace(",", ""))
    try: return float(s) if s not in ("", "-", ".") else None
    except ValueError: return None

def integer(v):
    n = num(v)
    return int(round(n)) if n is not None else None

def parse_date(v, expiry=False):
    """Accepts 2027-03-31, 31/03/2027, 03/27, 03/2027, Mar-2027, March 2027 ... Month-only dates become the last day of the month (expiry convention)."""
    if v in (None, ""): return None
    s = str(v).strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d/%m/%y", "%d-%m-%y", "%d %b %Y", "%d %B %Y", "%b %d, %Y"):
        try: return datetime.strptime(s, fmt).date()
        except ValueError: pass
    m = re.match(r"^(\d{1,2})\s*[/\-.]\s*(\d{2}|\d{4})$", s)
    if m:
        mo, y = int(m.group(1)), int(m.group(2)); y = y + 2000 if y < 100 else y
    else:
        m = re.match(r"^([A-Za-z]{3,9})[\s\-/.,]*(\d{2}|\d{4})$", s)
        if not m or m.group(1)[:3].lower() not in MONTHS: return None
        mo, y = MONTHS[m.group(1)[:3].lower()], int(m.group(2)); y = y + 2000 if y < 100 else y
    if not 1 <= mo <= 12: return None
    return date(y, mo, calendar.monthrange(y, mo)[1] if expiry else 1)

def size_norm(v):
    """'500MG' -> '500 mg', '10 ML' -> '10 ml', '1 LTR' -> '1 L'."""
    s = (str(v or "")).strip()
    m = re.match(r"^(\d+(?:\.\d+)?)\s*(mg|mcg|g|gm|kg|ml|l|ltr|litre|liter|litres|iu|%)\b(.*)$", s, re.I)
    if not m: return s
    unit = m.group(2).lower(); unit = {"gm": "g", "ltr": "L", "litre": "L", "liter": "L", "litres": "L", "l": "L"}.get(unit, unit)
    return f"{m.group(1)} {unit}{m.group(3)}".strip()

def normalize(raw: dict) -> dict:
    """Returns {draft, warnings}. draft has fixed keys the UI edits; dates are ISO strings."""
    raw = raw or {}
    sup, buy = raw.get("supplier") or {}, raw.get("buyer") or {}
    d = {
        "supplier_name": str(sup.get("name") or "").strip(), "supplier_address": str(sup.get("address") or "").strip(),
        "buyer_name": str(buy.get("name") or "").strip(), "buyer_address": str(buy.get("address") or "").strip(),
        "invoice_no": str(raw.get("invoice_no") or "").strip(),
        "invoice_date": (parse_date(raw.get("invoice_date")) or "") and parse_date(raw.get("invoice_date")).isoformat(),
        "items": [],
    }
    for it in raw.get("items") or []:
        if not isinstance(it, dict) or not str(it.get("name") or "").strip(): continue
        exp = parse_date(it.get("expiry"), expiry=True)
        d["items"].append({
            "name": re.sub(r"\s+", " ", str(it["name"]).strip()), "size": size_norm(it.get("size")),
            "batch_no": str(it.get("batch_no") or "").strip().upper(),
            "expiry": exp.isoformat() if exp else "", "qty": integer(it.get("qty")) or 0,
            "purchase_price": num(it.get("purchase_price")), "mrp": num(it.get("mrp")),
        })
    return {"draft": d, "warnings": validate(d)}

def validate(d: dict) -> list:
    w = []
    if not d.get("supplier_name"): w.append("Supplier name is missing.")
    if not d.get("items"): w.append("No medicine lines were found. Add them manually.")
    today = date.today()
    for i, it in enumerate(d.get("items", []), 1):
        p = f"Line {i} ({it.get('name') or '?'}): "
        if not it.get("name"): w.append(p + "name is missing.")
        if not it.get("batch_no"): w.append(p + "batch number is missing.")
        if not it.get("expiry"): w.append(p + "expiry date is missing or unreadable.")
        elif date.fromisoformat(it["expiry"]) < today: w.append(p + "already expired.")
        if not it.get("qty") or it["qty"] <= 0: w.append(p + "quantity must be above 0.")
        if it.get("purchase_price") is None: w.append(p + "purchase price is missing.")
    return w
