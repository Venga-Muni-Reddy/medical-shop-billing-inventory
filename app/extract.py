"""Pluggable document extraction.

To swap the OCR/AI engine: implement `Extractor.extract(data, mime) -> dict` returning the RAW shape below,
register it in EXTRACTORS and set EXTRACTOR=<name>. Normalisation/validation (normalize.py) is shared, so a new
engine never touches the database or API code.

RAW shape: {"supplier":{"name","address"}, "buyer":{"name","address"}, "invoice_no", "invoice_date",
            "items":[{"name","size","batch_no","expiry","qty","purchase_price","mrp"}]}
"""
import time, os, io, re, json, base64
import httpx

class ExtractionError(Exception): pass

class Extractor:
    name = "base"
    def extract(self, data: bytes, mime: str) -> dict: raise NotImplementedError

PROMPT = """You read supplier purchase invoices of a medical shop (pharmacy). The layout is unknown and differs by supplier.
Return ONLY one JSON object, no prose, no markdown, with exactly this shape:
{"supplier":{"name":"","address":""},"buyer":{"name":"","address":""},"invoice_no":"","invoice_date":"",
 "items":[{"name":"","size":"","batch_no":"","expiry":"","qty":0,"purchase_price":0,"mrp":0}]}
Rules:
- supplier = the company that SOLD the goods (invoice issuer). buyer = the shop that bought them.
- One item per medicine/product line. name = product name without strength. size = strength, pack size or volume such as "500 mg", "10 ml", "1 L".
- batch_no exactly as printed. expiry as printed (e.g. "03/2027" or "31-03-2027"). qty = number of units billed (include free qty only if printed as billed qty).
- purchase_price = rate per unit paid by the shop (not the line total). mrp = printed maximum retail price per unit if present, else null.
- Use null for anything not printed. Never invent values. Do not skip lines."""

def pdf_to_images(data: bytes, max_pages=3):
    import fitz
    doc = fitz.open(stream=data, filetype="pdf")
    out = []
    for p in list(doc)[:max_pages]:
        out.append(p.get_pixmap(dpi=130).tobytes("png"))
    return out

def parse_json(txt: str) -> dict:
    txt = re.sub(r"^```(?:json)?|```$", "", txt.strip(), flags=re.M).strip()
    m = re.search(r"\{.*\}", txt, re.S)
    if not m: raise ExtractionError("The AI reply did not contain data.")
    try: return json.loads(m.group(0))
    except json.JSONDecodeError as e: raise ExtractionError(f"The AI reply was not valid JSON ({e.msg}).")

class OpenRouterVision(Extractor):
    name = "openrouter-vision"
    def __init__(self):
        self.key = os.environ.get("OPENROUTER_API_KEY", "")
        self.models = [m.strip() for m in os.environ.get("OCR_MODELS", "google/gemma-4-31b-it:free,nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free,thinkingmachines/inkling:free,dots-studio/dots-3-note-preview:free,google/gemma-4-26b-a4b-it:free,thinkingmachines/inkling-small:free").split(",") if m.strip()]
        self.used = None
    def extract(self, data, mime):
        if not self.key: raise ExtractionError("AI extraction is not configured (no API key). Use manual entry.")
        images = pdf_to_images(data) if mime == "application/pdf" else [data]
        content = [{"type": "text", "text": PROMPT}] + [
            {"type": "image_url", "image_url": {"url": "data:%s;base64,%s" % ("image/png" if mime == "application/pdf" else mime, base64.b64encode(i).decode())}} for i in images]
        last = "no model answered"; t0 = time.time()
        for attempt in range(2):
            if attempt:
                if time.time() - t0 > 60: break
                time.sleep(5)
            busy = False
            for model in self.models:
                if time.time() - t0 > 80: break
                try:
                    r = httpx.post("https://openrouter.ai/api/v1/chat/completions", timeout=40,
                                   headers={"Authorization": f"Bearer {self.key}"},
                                   json={"model": model, "temperature": 0, "max_tokens": 4000, "messages": [{"role": "user", "content": content}]})
                    if r.status_code != 200:
                        last = f"{model}: HTTP {r.status_code}"; print("OCR_FAIL", model, r.status_code, r.text[:300], flush=True); busy = busy or r.status_code in (429, 502, 503); continue
                    msg = r.json()["choices"][0]["message"].get("content") or ""
                    raw = parse_json(msg)
                    self.used = model
                    return raw
                except (ExtractionError, httpx.HTTPError, KeyError, IndexError) as ex_:
                    last = f"{model}: {ex_}"
            if not busy: break
        raise ExtractionError("AI extraction failed (" + last + "). Please enter the invoice manually or try again.")

EXTRACTORS = {"openrouter-vision": OpenRouterVision}

def get_extractor() -> Extractor:
    return EXTRACTORS[os.environ.get("EXTRACTOR", "openrouter-vision")]()
