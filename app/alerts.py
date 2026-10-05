import os, threading, time
from datetime import date, timedelta
from . import db, mailer

def compute(owner):
    """Low-stock products and near-expiry / expired batches for one owner."""
    oid, days, dflt = owner["id"], owner["expiry_warn_days"], owner["default_low_stock"]
    low = db.q("""SELECT p.id, p.name, p.size, COALESCE(p.low_stock_threshold, %s) AS threshold, COALESCE(SUM(b.qty_on_hand),0)::int AS stock
                  FROM products p LEFT JOIN batches b ON b.product_id=p.id AND (b.expiry IS NULL OR b.expiry >= current_date)
                  WHERE p.owner_id=%s GROUP BY p.id HAVING COALESCE(SUM(b.qty_on_hand),0) <= COALESCE(p.low_stock_threshold, %s)
                  ORDER BY stock, p.name""", (dflt, oid, dflt))
    exp = db.q("""SELECT b.id, p.name, p.size, b.batch_no, b.expiry, b.qty_on_hand, (b.expiry - current_date) AS days_left
                  FROM batches b JOIN products p ON p.id=b.product_id
                  WHERE b.owner_id=%s AND b.qty_on_hand>0 AND b.expiry IS NOT NULL AND b.expiry <= current_date + %s
                  ORDER BY b.expiry""", (oid, days))
    return {"low_stock": low, "expiring": [e for e in exp if e["days_left"] >= 0], "expired": [e for e in exp if e["days_left"] < 0]}

def build_email(owner, a):
    lines = [f"Daily stock alert for {owner['shop_name'] or 'your shop'}", ""]
    if a["expired"]:
        lines.append("EXPIRED (still in stock):")
        lines += [f"  - {e['name']} {e['size']} | batch {e['batch_no']} | expired {e['expiry']} | {e['qty_on_hand']} left" for e in a["expired"]]; lines.append("")
    if a["expiring"]:
        lines.append(f"EXPIRING within {owner['expiry_warn_days']} days:")
        lines += [f"  - {e['name']} {e['size']} | batch {e['batch_no']} | expires {e['expiry']} ({e['days_left']} days) | {e['qty_on_hand']} left" for e in a["expiring"]]; lines.append("")
    if a["low_stock"]:
        lines.append("LOW STOCK:")
        lines += [f"  - {p['name']} {p['size']} | {p['stock']} in stock (alert at {p['threshold']} or less)" for p in a["low_stock"]]; lines.append("")
    return "\n".join(lines)

def run_for_owner(owner, force=False):
    """Sends one email per day containing only alerts not already sent today. Returns (sent, reason)."""
    a = compute(owner)
    today = date.today().isoformat()
    keys = {}
    for e in a["expired"]: keys[f"exp:{e['id']}"] = ("expired", e)
    for e in a["expiring"]: keys[f"near:{e['id']}"] = ("expiring", e)
    for p in a["low_stock"]: keys[f"low:{p['id']}:{today[:7]}"] = ("low", p)   # low stock: once per month per product until restocked
    done = {r["alert_key"] for r in db.q("SELECT alert_key FROM alert_log WHERE owner_id=%s", (owner["id"],))}
    fresh = {k for k in keys if k not in done} if not force else set(keys)
    if not fresh: return False, "nothing new to report"
    to = owner["alert_email"] or owner["email"]
    sub = {"expired": [], "expiring": [], "low": []}
    for k in fresh: sub[keys[k][0]].append(keys[k][1])
    payload = {"expired": sub["expired"], "expiring": sub["expiring"], "low_stock": sub["low"]}
    mailer.send(to, f"Stock alert: {len(fresh)} item(s) need attention", build_email(owner, payload))
    for k in fresh:
        db.q("INSERT INTO alert_log (owner_id, alert_key) VALUES (%s,%s) ON CONFLICT DO NOTHING", (owner["id"], k))
    return True, f"sent {len(fresh)} alert(s) to {to}"

def run_all():
    out = []
    if not mailer.configured(): return out
    for o in db.q("SELECT * FROM owners WHERE email_alerts"):
        try: out.append((o["id"], *run_for_owner(o)))
        except Exception as e: out.append((o["id"], False, f"error: {type(e).__name__}"))
    return out

def start_background():
    def loop():
        time.sleep(30)
        while True:
            try: run_all()
            except Exception: pass
            time.sleep(6 * 3600)
    threading.Thread(target=loop, daemon=True).start()
