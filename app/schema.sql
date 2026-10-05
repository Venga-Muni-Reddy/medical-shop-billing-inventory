CREATE TABLE IF NOT EXISTS owners (
  id SERIAL PRIMARY KEY,
  email TEXT UNIQUE NOT NULL,
  pw_hash TEXT NOT NULL,
  shop_name TEXT NOT NULL DEFAULT '',
  shop_address TEXT NOT NULL DEFAULT '',
  alert_email TEXT NOT NULL DEFAULT '',
  email_alerts BOOLEAN NOT NULL DEFAULT TRUE,
  expiry_warn_days INT NOT NULL DEFAULT 60,
  default_low_stock INT NOT NULL DEFAULT 10,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS sessions (
  token_hash TEXT PRIMARY KEY,
  owner_id INT NOT NULL REFERENCES owners(id) ON DELETE CASCADE,
  expires_at TIMESTAMPTZ NOT NULL
);
CREATE TABLE IF NOT EXISTS suppliers (
  id SERIAL PRIMARY KEY,
  owner_id INT NOT NULL REFERENCES owners(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  address TEXT NOT NULL DEFAULT '',
  UNIQUE (owner_id, name)
);
CREATE TABLE IF NOT EXISTS products (
  id SERIAL PRIMARY KEY,
  owner_id INT NOT NULL REFERENCES owners(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  size TEXT NOT NULL DEFAULT '',
  low_stock_threshold INT,
  UNIQUE (owner_id, name, size)
);
CREATE TABLE IF NOT EXISTS purchases (
  id SERIAL PRIMARY KEY,
  owner_id INT NOT NULL REFERENCES owners(id) ON DELETE CASCADE,
  status TEXT NOT NULL DEFAULT 'draft',          -- draft | confirmed
  source TEXT NOT NULL DEFAULT 'manual',         -- manual | ai
  extractor TEXT,
  filename TEXT,
  mime TEXT,
  doc BYTEA,
  draft JSONB NOT NULL DEFAULT '{}',
  warnings JSONB NOT NULL DEFAULT '[]',
  supplier_id INT REFERENCES suppliers(id),
  invoice_no TEXT,
  invoice_date DATE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  confirmed_at TIMESTAMPTZ
);
CREATE TABLE IF NOT EXISTS batches (
  id SERIAL PRIMARY KEY,
  owner_id INT NOT NULL REFERENCES owners(id) ON DELETE CASCADE,
  product_id INT NOT NULL REFERENCES products(id) ON DELETE CASCADE,
  supplier_id INT REFERENCES suppliers(id),
  purchase_id INT REFERENCES purchases(id) ON DELETE SET NULL,
  batch_no TEXT NOT NULL,
  expiry DATE,
  qty_received INT NOT NULL,
  qty_on_hand INT NOT NULL CHECK (qty_on_hand >= 0),
  purchase_price NUMERIC(12,2),
  mrp NUMERIC(12,2),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS batches_owner_idx ON batches (owner_id, product_id);
CREATE TABLE IF NOT EXISTS sales (
  id SERIAL PRIMARY KEY,
  owner_id INT NOT NULL REFERENCES owners(id) ON DELETE CASCADE,
  customer TEXT NOT NULL DEFAULT '',
  total NUMERIC(12,2) NOT NULL DEFAULT 0,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS sale_items (
  id SERIAL PRIMARY KEY,
  sale_id INT NOT NULL REFERENCES sales(id) ON DELETE CASCADE,
  batch_id INT REFERENCES batches(id) ON DELETE SET NULL,
  product_name TEXT NOT NULL,
  batch_no TEXT NOT NULL,
  qty INT NOT NULL,
  unit_price NUMERIC(12,2) NOT NULL
);
CREATE TABLE IF NOT EXISTS alert_log (
  owner_id INT NOT NULL REFERENCES owners(id) ON DELETE CASCADE,
  alert_key TEXT NOT NULL,
  sent_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (owner_id, alert_key)
);
