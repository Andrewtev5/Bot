from __future__ import annotations

from app.domain.models import Product


SAMPLE_PRODUCTS: list[Product] = [
    Product(
        id="led-lamp-10w",
        name="LED Lamp 10W",
        price=15.0,
        currency="PLN",
        category="lamp",
        description="Energy-efficient LED lamp with warm light for bedrooms and everyday home lighting.",
        tags=["warm light", "led", "bedroom"],
        keywords=["lamp", "led", "warm", "bedroom", "energy", "лампа", "свет", "теплый", "cieple", "swiatlo"],
        stock_status="in_stock",
        image_url="images/lamp1.jpg",
        attributes={"power": "10W", "light": "warm", "room": "bedroom"},
    ),
    Product(
        id="smart-wifi-lamp",
        name="Smart WiFi Lamp",
        price=40.0,
        currency="PLN",
        category="lamp",
        description="Smart lamp with phone control, brightness adjustment, and configurable color modes.",
        tags=["smart home", "wifi", "app control"],
        keywords=["lamp", "smart", "wifi", "app", "control", "лампа", "умная", "wifi", "smart home", "sterowanie"],
        stock_status="in_stock",
        image_url="images/lamp2.jpg",
        attributes={"control": "mobile app", "connectivity": "WiFi", "light": "adjustable"},
    ),
    Product(
        id="minimal-table-lamp",
        name="Minimal Table Lamp",
        price=32.0,
        currency="PLN",
        category="lamp",
        description="Compact premium desk lamp with a calm golden tone for workspaces and reading zones.",
        tags=["desk", "minimal", "workspace"],
        keywords=["lamp", "desk", "table", "reading", "work", "лампа", "настольная", "рабочая", "biurko", "stolowa"],
        stock_status="in_stock",
        image_url="images/lamp3.jpg",
        attributes={"style": "minimal", "room": "workspace", "light": "soft warm"},
    ),
    Product(
        id="nordic-glass-lamp",
        name="Nordic Glass Lamp",
        price=54.0,
        currency="PLN",
        category="lamp",
        description="Decorative glass lamp designed as a visual accent for living rooms and lounge spaces.",
        tags=["decor", "premium", "living room"],
        keywords=["lamp", "glass", "decor", "premium", "living room", "лампа", "стекло", "декор", "salon", "premium"],
        stock_status="in_stock",
        image_url="images/lamp4.jpg",
        attributes={"material": "glass", "style": "nordic", "room": "living room"},
    ),
]
