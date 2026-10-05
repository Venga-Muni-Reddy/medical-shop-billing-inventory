import os, re, time, hashlib, secrets, json
from collections import defaultdict, deque
from datetime import date
from typing import List, Optional
import bcrypt
from fastapi import FastAPI, HTTPException, Request, Response, UploadFile, File
from fastapi.responses import FileResponse, Response as RawResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from . import db, normalize, extract, alerts, mailer

SESSION_DAYS = 14
COOKIE = "ms_session"
EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,255}\.[^@\s]{2,}$")
MAX_UPLOAD = 6 * 1024 * 1024
MAX_OWNERS = int(os.environ.get("MAX_OWNERS", "50"))
ALLOWED = {"image/jpeg", "image/png", "image/webp", "application/pdf"}

app = FastAPI(title="Medical Shop Billing & Inventory")
_hits = defaultdict(deque)

def ip(req): return (req.headers.get("x-forwarded-for") or req.client.host or "?").split(",")[0].strip()
def limit(key, n, per):
    now = time.time(); dq = _hits[key]
    while dq and now - dq[0] > per: dq.popleft()
    if len(dq) >= n: raise HTTPException(429, "Too many requests. Please try again later.")
    dq.append(now)
def h(x): return hashlib.sha256(x.encode()).hexdigest()

@app.on_event("startup")
def startup():
    db.init(); alerts.start_background()

# ---------- auth ----------
def owner_of(req: Request):
    tok = req.cookies.get(COOKIE)
    o = tok and db.q("SELECT o.* FROM sessions s JOIN owners o ON o.id=s.owner_id WHERE s.token_hash=%s AND s.expires_at>now()", (h(tok),), one=True)
    if not o: raise HTTPException(401, "Please sign in")
    return o

class Creds(BaseModel):
    email: str = Field(min_length=5, max_length=320)
    password: str = Field(min_length=8, max_length=72)
    shop_name: str = Field(default="", max_length=100)

def start_session(resp, req, oid):
    tok = secrets.token_urlsafe(32)
    db.q("INSERT INTO sessions (token_hash, owner_id, expires_at) VALUES (%s,%s, now() + make_interval(days => %s))", (h(tok), oid, SESSION_DAYS))
    db.q("DELETE FROM sessions WHERE expires_at < now()")
    secure = req.headers.get("x-forwarded-proto", req.url.scheme) == "https"
    resp.set_cookie(COOKIE, tok, max_age=SESSION_DAYS * 86400, httponly=True, samesite="lax", secure=secure, path="/")

@app.post("/api/auth/signup")
def signup(b: Creds, req: Request, resp: Response):
    limit("signup:" + ip(req), 10, 3600)
    email = b.email.strip().lower()
    if not EMAIL_RE.match(email): raise HTTPException(400, "Enter a valid email address")
    if len(b.password.encode()) > 72: raise HTTPException(400, "Password must be at most 72 bytes")
    if db.q("SELECT count(*) AS n FROM owners", one=True)["n"] >= MAX_OWNERS: raise HTTPException(429, "Signups are full on this free deployment")
    pw = bcrypt.hashpw(b.password.encode(), bcrypt.gensalt()).decode()
    o = db.q("INSERT INTO owners (email, pw_hash, shop_name, alert_email) VALUES (%s,%s,%s,%s) ON CONFLICT (email) DO NOTHING RETURNING id",
             (email, pw, b.shop_name.strip(), email), one=True)
    if not o: raise HTTPException(409, "An account with this email already exists")
    start_session(resp, req, o["id"])
    return {"email": email}

@app.post("/api/auth/login")
def login(b: Creds, req: Request, resp: Response):
    limit("login:" + ip(req), 15, 900)
    o = db.q("SELECT * FROM owners WHERE email=%s", (b.email.strip().lower(),), one=True)
    try: ok = bool(o) and bcrypt.checkpw(b.password.encode(), o["pw_hash"].encode())
    except Exception: ok = False
    if not ok: raise HTTPException(401, "Wrong email or password")
    start_session(resp, req, o["id"])
    return {"email": o["email"]}

@app.post("/api/auth/logout")
def logout(req: Request, resp: Response):
    tok = req.cookies.get(COOKIE)
    if tok: db.q("DELETE FROM sessions WHERE token_hash=%s", (h(tok),))
    resp.delete_cookie(COOKIE, path="/")
    return {"ok": True}

@app.get("/api/auth/me")
def me(req: Request):
    try: o = owner_of(req)
    except HTTPException: return {"email": None}
    return {"email": o["email"], "shop_name": o["shop_name"]}

@app.get("/api/health")
def health(): return {"ok": True}

# ---------- settings ----------
class Settings(BaseModel):
    shop_name: str = Field(max_length=100)
    shop_address: str = Field(default="", max_length=300)
    alert_email: str = Field(max_length=320)
    email_alerts: bool
    expiry_warn_days: int = Field(ge=1, le=730)
    default_low_stock: int = Field(ge=0, le=100000)

def settings_out(o):
    return {k: o[k] for k in ("email", "shop_name", "shop_address", "alert_email", "email_alerts", "expiry_warn_days", "default_low_stock")} | {"email_provider": mailer.configured()}

@app.get("/api/settings")
def get_settings(req: Request): return settings_out(owner_of(req))

@app.put("/api/settings")
def put_settings(b: Settings, req: Request):
    o = owner_of(req)
    if b.alert_email and not EMAIL_RE.match(b.alert_email.strip()): raise HTTPException(400, "Enter a valid alert email")
    db.q("UPDATE owners SET shop_name=%s, shop_address=%s, alert_email=%s, email_alerts=%s, expiry_warn_days=%s, default_low_stock=%s WHERE id=%s",
         (b.shop_name.strip(), b.shop_address.strip(), b.alert_email.strip(), b.email_alerts, b.expiry_warn_days, b.default_low_stock, o["id"]))
    return settings_out(db.q("SELECT * FROM owners WHERE id=%s", (o["id"],), one=True))

# ---------- purchases ----------
class Item(BaseModel):
    name: str = Field(max_length=200)
    size: str = Field(default="", max_length=60)
    batch_no: str = Field(default="", max_length=60)
    expiry: str = ""
    qty: int = Field(default=0, ge=0, le=1000000)
    purchase_price: Optional[float] = Field(default=None, ge=0)
    mrp: Optional[float] = Field(default=None, ge=0)

class Draft(BaseModel):
    supplier_name: str = Field(default="", max_length=200)
    supplier_address: str = Field(default="", max_length=400)
    buyer_name: str = Field(default="", max_length=200)
    buyer_address: str = Field(default="", max_length=400)
    invoice_no: str = Field(default="", max_length=80)
    invoice_date: str = ""
    items: List[Item] = Field(default_factory=list, max_length=200)

def purchase_out(p, with_draft=True):
    out = {"id": p["id"], "status": p["status"], "source": p["source"], "extractor": p["extractor"], "filename": p["filename"],
           "has_doc": p.get("has_doc", False), "created_at": p["created_at"].isoformat(), "warnings": p["warnings"],
           "supplier": p["draft"].get("supplier_name"), "invoice_no": p["draft"].get("invoice_no"), "invoice_date": p["draft"].get("invoice_date"),
           "lines": len(p["draft"].get("items", []))}
    if with_draft: out["draft"] = p["draft"]
    return out

PCOLS = "id,owner_id,status,source,extractor,filename,mime,(doc IS NOT NULL) AS has_doc,draft,warnings,created_at"

def get_purchase(pid, oid):
    p = db.q(f"SELECT {PCOLS} FROM purchases WHERE id=%s AND owner_id=%s", (pid, oid), one=True)
    if not p: raise HTTPException(404, "Purchase not found")
    return p

@app.post("/api/purchases/extract")
async def extract_invoice(req: Request, file: UploadFile = File(...)):
    o = owner_of(req)
    limit("extract:" + str(o["id"]), 20, 3600)
    data = await file.read()
    mime = (file.content_type or "").lower()
    if mime == "image/jpg": mime = "image/jpeg"
    if mime not in ALLOWED: raise HTTPException(400, "Upload a JPG, PNG, WEBP image or a PDF")
    if len(data) > MAX_UPLOAD: raise HTTPException(400, "File is larger than 6 MB")
    ex = extract.get_extractor()
    warnings, raw = [], {}
    try:
        raw = ex.extract(data, mime)
    except extract.ExtractionError as e:
        warnings.append(str(e))
    except Exception as e:
        warnings.append(f"Extraction failed ({type(e).__name__}). Please enter the invoice manually.")
    n = normalize.normalize(raw)
    p = db.q("""INSERT INTO purchases (owner_id, source, extractor, filename, mime, doc, draft, warnings)
                VALUES (%s,'ai',%s,%s,%s,%s,%s::jsonb,%s::jsonb) RETURNING id""",
             (o["id"], getattr(ex, "used", None) or ex.name, (file.filename or "invoice")[:120], mime, data, json.dumps(n["draft"]), json.dumps(warnings + n["warnings"])), one=True)
    return purchase_out(get_purchase(p["id"], o["id"]))

@app.post("/api/purchases/{pid}/reextract")
def reextract(pid: int, req: Request):
    o = owner_of(req); limit("extract:" + str(o["id"]), 20, 3600)
    p = db.q("SELECT id, status, source, mime, doc FROM purchases WHERE id=%s AND owner_id=%s", (pid, o["id"]), one=True)
    if not p: raise HTTPException(404, "Purchase not found")
    if p["status"] != "draft" or not p["doc"]: raise HTTPException(409, "Nothing to re-read")
    ex = extract.get_extractor(); warnings, raw = [], {}
    try: raw = ex.extract(bytes(p["doc"]), p["mime"])
    except extract.ExtractionError as e: warnings.append(str(e))
    except Exception as e: warnings.append(f"Extraction failed ({type(e).__name__}). Please enter the invoice manually.")
    n = normalize.normalize(raw)
    db.q("UPDATE purchases SET draft=%s::jsonb, warnings=%s::jsonb, extractor=%s WHERE id=%s", (json.dumps(n["draft"]), json.dumps(warnings + n["warnings"]), getattr(ex, "used", None) or ex.name, pid))
    return purchase_out(get_purchase(pid, o["id"]))

@app.post("/api/purchases")
def new_manual_purchase(req: Request):
    o = owner_of(req)
    d = normalize.normalize({})["draft"]
    p = db.q("INSERT INTO purchases (owner_id, source, draft, warnings) VALUES (%s,'manual',%s::jsonb,'[]') RETURNING id", (o["id"], json.dumps(d)), one=True)
    return purchase_out(get_purchase(p["id"], o["id"]))

@app.get("/api/purchases")
def list_purchases(req: Request):
    o = owner_of(req)
    return [purchase_out(p, False) for p in db.q(f"SELECT {PCOLS} FROM purchases WHERE owner_id=%s ORDER BY id DESC LIMIT 100", (o["id"],))]

@app.get("/api/purchases/{pid}")
def one_purchase(pid: int, req: Request):
    o = owner_of(req); return purchase_out(get_purchase(pid, o["id"]))

@app.get("/api/purchases/{pid}/document")
def purchase_doc(pid: int, req: Request):
    o = owner_of(req)
    p = db.q("SELECT mime, doc, filename FROM purchases WHERE id=%s AND owner_id=%s", (pid, o["id"]), one=True)
    if not p or not p["doc"]: raise HTTPException(404, "No document")
    return RawResponse(bytes(p["doc"]), media_type=p["mime"], headers={"Content-Disposition": f'inline; filename="{(p["filename"] or "invoice").replace(chr(34), "")}"'})

@app.put("/api/purchases/{pid}")
def save_draft(pid: int, b: Draft, req: Request):
    o = owner_of(req); p = get_purchase(pid, o["id"])
    if p["status"] != "draft": raise HTTPException(409, "This purchase is already confirmed")
    d = normalize.normalize({"supplier": {"name": b.supplier_name, "address": b.supplier_address}, "buyer": {"name": b.buyer_name, "address": b.buyer_address},
                              "invoice_no": b.invoice_no, "invoice_date": b.invoice_date, "items": [i.model_dump() for i in b.items]})
    db.q("UPDATE purchases SET draft=%s::jsonb, warnings=%s::jsonb WHERE id=%s", (json.dumps(d["draft"]), json.dumps(d["warnings"]), pid))
    return purchase_out(get_purchase(pid, o["id"]))

@app.delete("/api/purchases/{pid}")
def del_draft(pid: int, req: Request):
    o = owner_of(req); p = get_purchase(pid, o["id"])
    if p["status"] != "draft": raise HTTPException(409, "Confirmed purchases cannot be deleted")
    db.q("DELETE FROM purchases WHERE id=%s", (pid,)); return {"ok": True}

@app.post("/api/purchases/{pid}/confirm")
def confirm(pid: int, req: Request):
    o = owner_of(req); p = get_purchase(pid, o["id"]); d = p["draft"]
    if p["status"] != "draft": raise HTTPException(409, "Already confirmed")
    errs = []
    if not d.get("supplier_name"): errs.append("Supplier name is required")
    if not d.get("items"): errs.append("Add at least one medicine line")
    for i, it in enumerate(d.get("items", []), 1):
        if not it["name"] or not it["batch_no"] or not it["expiry"] or it["qty"] <= 0:
            errs.append(f"Line {i}: name, batch number, expiry date and quantity are required")
    if errs: raise HTTPException(400, "; ".join(errs[:5]))
    with db.tx() as c:
        sup = c.execute("""INSERT INTO suppliers (owner_id, name, address) VALUES (%s,%s,%s)
                           ON CONFLICT (owner_id, name) DO UPDATE SET address = CASE WHEN EXCLUDED.address<>'' THEN EXCLUDED.address ELSE suppliers.address END RETURNING id""",
                         (o["id"], d["supplier_name"], d.get("supplier_address", ""))).fetchone()
        for it in d["items"]:
            pr = c.execute("INSERT INTO products (owner_id, name, size) VALUES (%s,%s,%s) ON CONFLICT (owner_id, name, size) DO UPDATE SET name=EXCLUDED.name RETURNING id",
                           (o["id"], it["name"], it["size"])).fetchone()
            c.execute("""INSERT INTO batches (owner_id, product_id, supplier_id, purchase_id, batch_no, expiry, qty_received, qty_on_hand, purchase_price, mrp)
                         VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                      (o["id"], pr["id"], sup["id"], pid, it["batch_no"], it["expiry"], it["qty"], it["qty"], it["purchase_price"], it["mrp"]))
        c.execute("UPDATE purchases SET status='confirmed', confirmed_at=now(), supplier_id=%s, invoice_no=%s, invoice_date=%s WHERE id=%s",
                  (sup["id"], d.get("invoice_no") or None, d.get("invoice_date") or None, pid))
    return {"ok": True, "batches_added": len(d["items"])}

# ---------- inventory ----------
def batch_rows(oid, where="", params=()):
    return db.q(f"""SELECT b.id, p.id AS product_id, p.name, p.size, b.batch_no, b.expiry, b.qty_on_hand, b.qty_received, b.purchase_price, b.mrp,
                           s.name AS supplier, (b.expiry - current_date) AS days_left
                    FROM batches b JOIN products p ON p.id=b.product_id LEFT JOIN suppliers s ON s.id=b.supplier_id
                    WHERE b.owner_id=%s {where} ORDER BY p.name, b.expiry NULLS LAST""", (oid, *params))

def jsonable(rows):
    out = []
    for r in rows:
        r = dict(r)
        for k, v in r.items():
            if hasattr(v, "isoformat"): r[k] = v.isoformat()
            elif v.__class__.__name__ == "Decimal": r[k] = float(v)
        out.append(r)
    return out

@app.get("/api/inventory")
def inventory(req: Request, show_empty: bool = False):
    o = owner_of(req)
    rows = batch_rows(o["id"], "" if show_empty else "AND b.qty_on_hand > 0")
    low = {p["id"] for p in alerts.compute(o)["low_stock"]}
    res = jsonable(rows)
    for r in res:
        r["expired"] = r["days_left"] is not None and r["days_left"] < 0
        r["near_expiry"] = r["days_left"] is not None and 0 <= r["days_left"] <= o["expiry_warn_days"]
        r["low_stock"] = r["product_id"] in low
    return res

class BatchEdit(BaseModel):
    batch_no: str = Field(max_length=60)
    expiry: str
    qty_on_hand: int = Field(ge=0, le=1000000)
    purchase_price: Optional[float] = Field(default=None, ge=0)
    mrp: Optional[float] = Field(default=None, ge=0)

@app.put("/api/batches/{bid}")
def edit_batch(bid: int, b: BatchEdit, req: Request):
    o = owner_of(req)
    exp = normalize.parse_date(b.expiry, expiry=True)
    if not exp or not b.batch_no.strip(): raise HTTPException(400, "Batch number and a valid expiry date are required")
    r = db.q("UPDATE batches SET batch_no=%s, expiry=%s, qty_on_hand=%s, purchase_price=%s, mrp=%s WHERE id=%s AND owner_id=%s RETURNING id",
             (b.batch_no.strip().upper(), exp, b.qty_on_hand, b.purchase_price, b.mrp, bid, o["id"]), one=True)
    if not r: raise HTTPException(404, "Batch not found")
    return {"ok": True}

class Threshold(BaseModel):
    low_stock_threshold: Optional[int] = Field(default=None, ge=0, le=100000)

@app.put("/api/products/{pid}/threshold")
def product_threshold(pid: int, b: Threshold, req: Request):
    o = owner_of(req)
    r = db.q("UPDATE products SET low_stock_threshold=%s WHERE id=%s AND owner_id=%s RETURNING id", (b.low_stock_threshold, pid, o["id"]), one=True)
    if not r: raise HTTPException(404, "Product not found")
    return {"ok": True}

@app.get("/api/alerts")
def alert_view(req: Request):
    o = owner_of(req)
    a = alerts.compute(o)
    return {k: jsonable(v) for k, v in a.items()} | {"expiry_warn_days": o["expiry_warn_days"]}

@app.post("/api/alerts/test")
def alert_test(req: Request):
    o = owner_of(req)
    limit("mailtest:" + str(o["id"]), 5, 3600)
    if not mailer.configured(): raise HTTPException(503, "Email sending is not configured on the server yet")
    to = o["alert_email"] or o["email"]
    try:
        mailer.send(to, "Test alert from your medical shop app", alerts.build_email(o, alerts.compute(o)) + "\n(This is a test email.)")
    except Exception as e:
        raise HTTPException(502, f"Email failed: {type(e).__name__}: {str(e)[:120]}")
    return {"ok": True, "sent_to": to}

@app.post("/api/alerts/run")
def alert_run(req: Request):
    """Daily check. Safe to call publicly: it only emails each owner's own alert address and never repeats an alert."""
    limit("run:" + ip(req), 30, 3600)
    return {"results": [{"sent": s, "note": n} for _, s, n in alerts.run_all()]}

# ---------- sales ----------
@app.get("/api/products/search")
def search_products(req: Request, q: str = ""):
    o = owner_of(req)
    like = "%" + q.strip().lower().replace("%", "") + "%"
    rows = batch_rows(o["id"], "AND b.qty_on_hand > 0 AND (b.expiry IS NULL OR b.expiry >= current_date) AND lower(p.name) LIKE %s", (like,))
    prods = {}
    for r in jsonable(rows):
        p = prods.setdefault(r["product_id"], {"product_id": r["product_id"], "name": r["name"], "size": r["size"], "batches": []})
        p["batches"].append({k: r[k] for k in ("id", "batch_no", "expiry", "qty_on_hand", "mrp", "purchase_price", "days_left")})
    return list(prods.values())[:30]

class SaleLine(BaseModel):
    batch_id: int
    qty: int = Field(gt=0, le=100000)
    unit_price: float = Field(ge=0)

class Sale(BaseModel):
    customer: str = Field(default="", max_length=120)
    lines: List[SaleLine] = Field(min_length=1, max_length=100)

@app.post("/api/sales")
def make_sale(b: Sale, req: Request):
    o = owner_of(req)
    total = 0
    with db.tx() as c:
        sale = c.execute("INSERT INTO sales (owner_id, customer) VALUES (%s,%s) RETURNING id", (o["id"], b.customer.strip())).fetchone()
        for ln in b.lines:
            r = c.execute("""UPDATE batches SET qty_on_hand = qty_on_hand - %s WHERE id=%s AND owner_id=%s AND qty_on_hand >= %s
                             AND (expiry IS NULL OR expiry >= current_date)
                             RETURNING batch_no, product_id""", (ln.qty, ln.batch_id, o["id"], ln.qty)).fetchone()
            if not r: raise HTTPException(409, "Not enough stock in the selected batch, or the batch is expired")
            pr = c.execute("SELECT name, size FROM products WHERE id=%s", (r["product_id"],)).fetchone()
            c.execute("INSERT INTO sale_items (sale_id, batch_id, product_name, batch_no, qty, unit_price) VALUES (%s,%s,%s,%s,%s,%s)",
                      (sale["id"], ln.batch_id, (pr["name"] + " " + pr["size"]).strip(), r["batch_no"], ln.qty, ln.unit_price))
            total += ln.qty * ln.unit_price
        c.execute("UPDATE sales SET total=%s WHERE id=%s", (round(total, 2), sale["id"]))
    return {"id": sale["id"], "total": round(total, 2)}

@app.get("/api/sales")
def sales(req: Request):
    o = owner_of(req)
    rows = db.q("SELECT id, customer, total, created_at FROM sales WHERE owner_id=%s ORDER BY id DESC LIMIT 100", (o["id"],))
    items = db.q("SELECT i.* FROM sale_items i JOIN sales s ON s.id=i.sale_id WHERE s.owner_id=%s AND s.id = ANY(%s)", (o["id"], [r["id"] for r in rows] or [0]))
    by = {}
    for i in jsonable(items): by.setdefault(i["sale_id"], []).append(i)
    return [r | {"items": by.get(r["id"], [])} for r in jsonable(rows)]

@app.get("/api/summary")
def summary(req: Request):
    o = owner_of(req); a = alerts.compute(o)
    s = db.q("""SELECT (SELECT COALESCE(SUM(qty_on_hand),0) FROM batches WHERE owner_id=%s) AS units,
                       (SELECT count(*) FROM products WHERE owner_id=%s) AS products,
                       (SELECT COALESCE(SUM(total),0) FROM sales WHERE owner_id=%s AND created_at::date = current_date) AS sales_today,
                       (SELECT count(*) FROM sales WHERE owner_id=%s AND created_at::date = current_date) AS bills_today""", (o["id"],) * 4, one=True)
    return {"units": int(s["units"]), "products": s["products"], "sales_today": float(s["sales_today"]), "bills_today": s["bills_today"],
            "low_stock": len(a["low_stock"]), "expiring": len(a["expiring"]), "expired": len(a["expired"])}

# ---------- frontend ----------
DIST = os.path.join(os.path.dirname(__file__), "..", "frontend", "dist")
if os.path.isdir(DIST):
    app.mount("/assets", StaticFiles(directory=os.path.join(DIST, "assets")), name="assets")
    @app.get("/{path:path}")
    def spa(path: str):
        f = os.path.join(DIST, path)
        return FileResponse(f if path and os.path.isfile(f) else os.path.join(DIST, "index.html"))
