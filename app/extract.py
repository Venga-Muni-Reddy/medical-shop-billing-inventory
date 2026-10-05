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

def pdf_text(data: bytes, max_pages=3) -> str:
    import fitz
    doc = fitz.open(stream=data, filetype="pdf")
    t = "\n".join(p.get_text() for p in list(doc)[:max_pages]).strip()
    return t if len(t) > 150 else ""

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
        self.models = [m.strip() for m in os.environ.get("OCR_MODELS", "dots-studio/dots-3-note-preview:free,nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free,google/gemma-4-31b-it:free,google/gemma-4-26b-a4b-it:free").split(",") if m.strip()]
        self.used = None
    def extract(self, data, mime):
        if not self.key: raise ExtractionError("AI extraction is not configured (no API key). Use manual entry.")
        images, text = ([data], "")
        if mime == "application/pdf":
            images, text = pdf_to_images(data), pdf_text(data)
        img_parts = [{"type": "image_url", "image_url": {"url": "data:%s;base64,%s" % ("image/png" if mime == "application/pdf" else mime, base64.b64encode(i).decode())}} for i in images]
        extra = ("\n\nThe document's own text layer (may lose table structure; use together with the image if given):\n" + text[:12000]) if text else ""
        plans = []
        if text:  # text-only first: faster and more reliable than reading pixels
            tm = [m.strip() for m in os.environ.get("TEXT_MODELS", "dots-studio/dots-3-note-preview:free,google/gemma-4-31b-it:free,nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free,nvidia/nemotron-3-super-120b-a12b:free").split(",") if m.strip()]
            plans += [(m, [{"type": "text", "text": PROMPT + extra}]) for m in tm]
        plans += [(m, [{"type": "text", "text": PROMPT + extra}] + img_parts) for m in self.models]
        errs, t0 = [], time.time()
        for rnd in range(2):
            if rnd:
                if time.time() - t0 > 45: break
                time.sleep(5)
            busy = False
            for model, content in plans:
                if time.time() - t0 > 70: break
                try:
                    r = httpx.post("https://openrouter.ai/api/v1/chat/completions", timeout=30,
                                   headers={"Authorization": f"Bearer {self.key}"},
                                   json={"model": model, "temperature": 0, "max_tokens": 6000, "messages": [{"role": "user", "content": content}]})
                    if r.status_code != 200:
                        errs.append(f"{model.split('/')[-1]}: HTTP {r.status_code}"); busy = busy or r.status_code in (429, 502, 503)
                        print("OCR_FAIL", model, r.status_code, r.text[:200], flush=True); continue
                    j = r.json()
                    if "choices" not in j:
                        print("OCR_FAIL", model, "no choices", str(j)[:200], flush=True); raise ExtractionError("model busy")
                    m0 = j["choices"][0]["message"]
                    msg = m0.get("content") or ""
                    if "{" not in msg: msg = msg or (m0.get("reasoning") or "")
                    if "{" not in msg: print("OCR_FAIL", model, "reply head", repr(msg[:150]), j["choices"][0].get("finish_reason"), flush=True)
                    raw = parse_json(msg)
                    if not (raw.get("items") or raw.get("supplier")): raise ExtractionError("empty result")
                    self.used = model + (" (text)" if len(content) == 1 else "")
                    return raw
                except (ExtractionError, httpx.HTTPError, KeyError, IndexError, ValueError, AttributeError) as ex_:
                    errs.append(f"{model.split('/')[-1]}: {ex_}"); busy = True
                    print("OCR_FAIL", model, repr(ex_)[:200], flush=True)
            if not busy: break
        raise ExtractionError("AI extraction failed on every model (" + "; ".join(errs[-4:]) + "). Press retry in a minute or enter it manually.")

EXTRACTORS = {"openrouter-vision": OpenRouterVision}

def get_extractor() -> Extractor:
    return EXTRACTORS[os.environ.get("EXTRACTOR", "openrouter-vision")]()
