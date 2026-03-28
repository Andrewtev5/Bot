CREATE TABLE IF NOT EXISTS products (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    price REAL NOT NULL,
    currency TEXT NOT NULL DEFAULT 'PLN',
    category TEXT NOT NULL,
    description TEXT NOT NULL,
    stock_status TEXT NOT NULL DEFAULT 'unknown',
    image_url TEXT
);
