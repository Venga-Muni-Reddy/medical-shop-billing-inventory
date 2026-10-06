"""Email sending. Providers are tried in order of configuration: SMTP (e.g. Gmail app password), then Brevo HTTP API (any recipient), then Resend HTTP API."""
import os, re, smtplib, ssl
from email.message import EmailMessage
import httpx

def configured():
    if os.environ.get("SMTP_HOST") and os.environ.get("SMTP_USER") and os.environ.get("SMTP_PASS"): return "smtp"
    if os.environ.get("BREVO_API_KEY") and os.environ.get("MAIL_FROM"): return "brevo"
    if os.environ.get("RESEND_API_KEY"): return "resend"
    return None

def send(to: str, subject: str, body: str):
    prov = configured()
    if not prov: raise RuntimeError("Email is not configured on the server")
    sender = os.environ.get("MAIL_FROM") or os.environ.get("SMTP_USER") or "onboarding@resend.dev"
    if prov == "brevo":
        mm = re.match(r"\s*(?:\"?([^\"<]*?)\"?\s*)?<([^>]+)>\s*$", sender)
        name, addr = (mm.group(1) or "MedShop", mm.group(2)) if mm else ("MedShop", sender.strip())
        r = httpx.post("https://api.brevo.com/v3/smtp/email", timeout=20, headers={"api-key": os.environ["BREVO_API_KEY"], "accept": "application/json"},
                       json={"sender": {"name": name.strip() or "MedShop", "email": addr}, "to": [{"email": to}], "subject": subject, "textContent": body})
        if r.status_code >= 300: raise RuntimeError(f"Brevo error {r.status_code}: {r.text[:150]}")
    elif prov == "smtp":
        m = EmailMessage(); m["From"], m["To"], m["Subject"] = sender, to, subject; m.set_content(body)
        host, port = os.environ["SMTP_HOST"], int(os.environ.get("SMTP_PORT", "465"))
        if port == 465:
            with smtplib.SMTP_SSL(host, port, context=ssl.create_default_context(), timeout=20) as s:
                s.login(os.environ["SMTP_USER"], os.environ["SMTP_PASS"]); s.send_message(m)
        else:
            with smtplib.SMTP(host, port, timeout=20) as s:
                s.starttls(context=ssl.create_default_context()); s.login(os.environ["SMTP_USER"], os.environ["SMTP_PASS"]); s.send_message(m)
    else:
        r = httpx.post("https://api.resend.com/emails", timeout=20, headers={"Authorization": "Bearer " + os.environ["RESEND_API_KEY"]},
                       json={"from": sender, "to": [to], "subject": subject, "text": body})
        if r.status_code >= 300: raise RuntimeError(f"Resend error {r.status_code}: {r.text[:150]}")
