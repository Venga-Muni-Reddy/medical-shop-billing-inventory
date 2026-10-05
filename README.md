# Medical Shop Billing & Inventory (Owner-only MVP)

FastAPI + PostgreSQL + React. One role: the shop Owner.

Features: supplier invoice upload with AI extraction (vision LLM) and manual edit, batch-level inventory, billing with batch selection and automatic stock reduction, low-stock and near-expiry views, configurable email alerts, owner login (bcrypt + server sessions).

## Run locally
    pip install -r requirements.txt
    export DATABASE_URL=postgresql://...  OPENROUTER_API_KEY=...
    cd frontend && npm install && npm run build && cd ..
    uvicorn app.main:app

## Swapping the OCR/AI engine
Implement `Extractor.extract(data, mime) -> raw dict` in `app/extract.py`, add it to `EXTRACTORS`, set `EXTRACTOR=<name>`. Normalisation and validation (`app/normalize.py`) are shared.

## Environment
DATABASE_URL, OPENROUTER_API_KEY, optional OCR_MODELS, EXTRACTOR, and for email either SMTP_HOST/SMTP_PORT/SMTP_USER/SMTP_PASS/MAIL_FROM or RESEND_API_KEY.
