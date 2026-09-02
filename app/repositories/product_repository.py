from __future__ import annotations

import re
import unicodedata
from typing import Any, Protocol

from app.core.config import Settings
from app.data.sample_products import SAMPLE_PRODUCTS
from app.domain.models import Product


class ProductRepository(Protocol):
    def list_products(self) -> list[Product]:
        ...

    def get_product(self, product_id: str) -> Product | None:
        ...

    def search_products(self, query: str, limit: int = 5) -> list[Product]:
        ...


class InMemoryProductRepository:
    def __init__(self, products: list[Product] | None = None) -> None:
        self._products = {product.id: product for product in (products or SAMPLE_PRODUCTS)}

    def list_products(self) -> list[Product]:
        return list(self._products.values())

    def get_product(self, product_id: str) -> Product | None:
        return self._products.get(product_id)

    def search_products(self, query: str, limit: int = 5) -> list[Product]:
        normalized = normalize_text(query)
        if not normalized:
            return self.list_products()[:limit]

        scored: list[tuple[int, Product]] = []
        for product in self._products.values():
            score = score_product(product, normalized)
            if score > 0:
                scored.append((score, product))

        scored.sort(key=lambda item: item[0], reverse=True)
        return [product for _, product in scored[:limit]]


class SqlServerProductRepository:
    def __init__(self, connection_string: str) -> None:
        self._connection_string = connection_string
        self._columns: set[str] | None = None

    def list_products(self) -> list[Product]:
        rows = self._fetch_all(f"SELECT TOP (500) {self._select_clause()} FROM products ORDER BY name")
        return [map_sql_server_product(row) for row in rows]

    def get_product(self, product_id: str) -> Product | None:
        rows = self._fetch_all(f"SELECT TOP (1) {self._select_clause()} FROM products WHERE id = ?", (product_id,))
        return map_sql_server_product(rows[0]) if rows else None

    def search_products(self, query: str, limit: int = 5) -> list[Product]:
        normalized = normalize_text(query)
        if not normalized:
            return self.list_products()[:limit]

        products = self.list_products()
        scored: list[tuple[int, Product]] = []
        for product in products:
            score = score_product(product, normalized)
            if score > 0:
                scored.append((score, product))

        scored.sort(key=lambda item: item[0], reverse=True)
        if scored:
            return [product for _, product in scored[:limit]]

        if is_lamp_query(normalized):
            light_preference = light_preference_for_query(normalized)
            if light_preference:
                products = [
                    product
                    for product in products
                    if is_product_allowed_for_light_preference(product, light_preference)
                ]
            return products[:limit]

        return []

    def _select_clause(self) -> str:
        columns = self._get_columns()
        if {"name_pl", "name_en", "tag_pl", "tag_en", "description_pl", "description_en", "image"}.issubset(columns):
            return """
                id,
                COALESCE(NULLIF(name_pl, ''), NULLIF(name_en, ''), id) AS name,
                price,
                COALESCE(NULLIF(currency, ''), 'PLN') AS currency,
                COALESCE(NULLIF(tag_pl, ''), NULLIF(tag_en, ''), 'lampa') AS category,
                COALESCE(NULLIF(description_pl, ''), NULLIF(description_en, ''), '') AS description,
                CAST('in_stock' AS NVARCHAR(50)) AS stock_status,
                image AS image_url
            """

        return """
            id,
            name,
            price,
            COALESCE(NULLIF(currency, ''), 'PLN') AS currency,
            COALESCE(NULLIF(category, ''), 'lampa') AS category,
            COALESCE(description, '') AS description,
            COALESCE(NULLIF(stock_status, ''), 'unknown') AS stock_status,
            image_url
        """

    def _search_columns(self) -> list[str]:
        columns = self._get_columns()
        if {"name_pl", "name_en", "tag_pl", "tag_en", "description_pl", "description_en"}.issubset(columns):
            return [
                "id",
                "name_pl",
                "name_en",
                "description_pl",
                "description_en",
                "tag_pl",
                "tag_en",
            ]

        return ["id", "name", "description", "category"]

    def _get_columns(self) -> set[str]:
        if self._columns is None:
            rows = self._fetch_all(
                """
                SELECT LOWER(COLUMN_NAME) AS column_name
                FROM INFORMATION_SCHEMA.COLUMNS
                WHERE TABLE_SCHEMA = 'dbo'
                  AND TABLE_NAME = 'products'
                """
            )
            self._columns = {str(row.column_name).lower() for row in rows}
        return self._columns

    def _fetch_all(self, query: str, params: tuple[Any, ...] = ()) -> list[Any]:
        try:
            import pyodbc
        except ImportError as error:
            raise RuntimeError(
                "pyodbc is required for PRODUCT_DB_MODE=mssql. "
                "Install it and Microsoft ODBC Driver for SQL Server."
            ) from error

        if not self._connection_string:
            raise RuntimeError("SQL_SERVER_CONNECTION_STRING is empty.")

        connection = pyodbc.connect(self._connection_string)
        try:
            cursor = connection.cursor()
            cursor.execute(query, params)
            return list(cursor.fetchall())
        finally:
            connection.close()


def build_product_repository(settings: Settings) -> ProductRepository:
    if settings.product_db_mode == "mssql":
        return SqlServerProductRepository(settings.sql_server_connection_string)

    return InMemoryProductRepository()


def normalize_text(value: str) -> str:
    return " ".join(re.sub(r"[^\wąćęłńóśźżĄĆĘŁŃÓŚŹŻ]+", " ", value.lower()).strip().split())


def comparable_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", normalize_text(value))
    without_marks = "".join(character for character in normalized if not unicodedata.combining(character))
    return without_marks.replace("ł", "l")


STOP_WORDS = {
    "a",
    "albo",
    "and",
    "by",
    "czy",
    "do",
    "dla",
    "daj",
    "i",
    "in",
    "jakas",
    "jakies",
    "jakis",
    "mi",
    "mnie",
    "na",
    "or",
    "oraz",
    "pokaz",
    "poprosze",
    "prosze",
    "the",
    "w",
    "with",
    "z",
}

QUERY_SYNONYMS = {
    "lampka": {"lampa", "lamp", "light"},
    "lampki": {"lampa", "lamp", "light"},
    "lampke": {"lampa", "lamp", "light"},
    "lampy": {"lampa", "lamp", "light"},
    "zarowka": {"lampa", "led", "light"},
    "zarowke": {"lampa", "led", "light"},
    "zarowki": {"lampa", "led", "light"},
    "swiatlo": {"lighting", "light", "lampa"},
    "swiatla": {"lighting", "light", "lampa"},
    "bathroom": {"lazienka", "restroom", "lustro", "kinkiet", "plafon", "jasne", "neutralne", "led", "light", "lighting", "lampa"},
    "biale": {"jasne", "white", "clear", "led"},
    "biala": {"jasne", "white", "clear", "led"},
    "bialy": {"jasne", "white", "clear", "led"},
    "bialym": {"jasne", "white", "clear", "neutralne", "led"},
    "neutralna": {"biale", "jasne", "white", "clear", "led"},
    "neutralne": {"biale", "jasne", "white", "clear", "led"},
    "neutralny": {"biale", "jasne", "white", "clear", "led"},
    "jasna": {"biale", "neutralne", "white", "clear", "led"},
    "jasne": {"biale", "neutralne", "white", "clear", "led"},
    "jasny": {"biale", "neutralne", "white", "clear", "led"},
    "default": {"biale", "neutralne", "jasne", "led"},
    "domyslna": {"biale", "neutralne", "jasne", "led"},
    "domyslne": {"biale", "neutralne", "jasne", "led"},
    "klasyczna": {"biale", "neutralne", "jasne", "led"},
    "klasyczne": {"biale", "neutralne", "jasne", "led"},
    "normalna": {"biale", "neutralne", "jasne", "led"},
    "normalne": {"biale", "neutralne", "jasne", "led"},
    "standardowa": {"biale", "neutralne", "jasne", "led"},
    "standardowe": {"biale", "neutralne", "jasne", "led"},
    "zwykla": {"biale", "neutralne", "jasne", "led"},
    "zwykle": {"biale", "neutralne", "jasne", "led"},
    "ciepla": {"zolte", "warm", "ambient", "cozy"},
    "cieple": {"zolte", "warm", "ambient", "cozy"},
    "cieply": {"zolte", "warm", "ambient", "cozy"},
    "zolta": {"cieple", "warm", "ambient", "cozy"},
    "zolte": {"cieple", "warm", "ambient", "cozy"},
    "zolty": {"cieple", "warm", "ambient", "cozy"},
    "lazienki": {"lazienka", "bathroom", "lustro", "kinkiet", "plafon", "jasne", "neutralne", "led"},
    "lazienka": {"bathroom", "lustro", "kinkiet", "plafon", "jasne", "neutralne", "led"},
    "restroom": {"bathroom", "lazienka", "mirror", "wall", "sconce", "ceiling", "jasne", "neutralne", "led", "light", "lighting", "lampa"},
    "toilet": {"bathroom", "lazienka", "mirror", "wall", "sconce", "ceiling", "jasne", "neutralne", "led", "light", "lighting", "lampa"},
    "washroom": {"bathroom", "lazienka", "mirror", "wall", "sconce", "ceiling", "jasne", "neutralne", "led", "light", "lighting", "lampa"},
    "magia": {"magiczna", "magic", "rgb", "kolorowa", "teczowa", "aura", "galaxy", "sunset", "neon", "projektor"},
    "magiczna": {"magic", "magical", "rgb", "kolorowa", "teczowa", "aura", "galaxy", "sunset", "neon", "projektor"},
    "magiczne": {"magic", "magical", "rgb", "kolorowa", "teczowa", "aura", "galaxy", "sunset", "neon", "projektor"},
    "magic": {"magiczna", "magical", "rgb", "colorful", "rainbow", "aura", "galaxy", "sunset", "neon", "projector"},
    "magical": {"magiczna", "magic", "rgb", "colorful", "rainbow", "aura", "galaxy", "sunset", "neon", "projector"},
    "teczowa": {"rgb", "kolorowa", "colorful", "rainbow", "barwna", "neon", "aura"},
    "teczowe": {"rgb", "kolorowe", "colorful", "rainbow", "barwne", "neon", "aura"},
    "rainbow": {"rgb", "colorful", "kolorowa", "teczowa", "neon", "aura"},
    "kolorowa": {"rgb", "barwna", "teczowa", "colorful", "rainbow", "neon"},
    "kolorowe": {"rgb", "barwne", "teczowe", "colorful", "rainbow", "neon"},
    "colorful": {"rgb", "kolorowa", "teczowa", "rainbow", "neon", "aura"},
    "okragla": {"kula", "kulista", "globe", "sphere", "ring", "halo", "pierścien"},
    "okragle": {"kula", "kulista", "globe", "sphere", "ring", "halo", "pierścien"},
    "round": {"kula", "kulista", "globe", "sphere", "ring", "halo"},
    "kula": {"okragla", "kulista", "globe", "sphere", "ball"},
    "kulka": {"okragla", "kula", "globe", "sphere", "ball"},
    "globe": {"kula", "kulista", "sphere", "round"},
    "sphere": {"kula", "kulista", "globe", "round"},
    "pierścien": {"ring", "halo", "okragla", "led"},
    "pierscien": {"ring", "halo", "okragla", "led"},
    "ring": {"pierścien", "pierscien", "halo", "round", "led"},
    "halo": {"pierścien", "pierscien", "ring", "round", "led"},
    "aplikacja": {"smart", "wifi", "telefon", "sterowanie"},
    "aplikacji": {"smart", "wifi", "telefon", "sterowanie"},
    "telefon": {"smart", "wifi", "aplikacja", "sterowanie"},
    "phone": {"smart", "wifi", "app", "control"},
    "app": {"smart", "wifi", "phone", "control"},
    "inteligentna": {"smart", "wifi", "aplikacja", "rgb", "led"},
    "inteligentne": {"smart", "wifi", "aplikacja", "rgb", "led"},
    "biurko": {"biurkowa", "desk", "table", "czytanie", "praca"},
    "biurka": {"biurkowa", "desk", "table", "czytanie", "praca"},
    "desk": {"biurko", "biurkowa", "table", "reading", "work"},
    "czytania": {"czytanie", "reading", "biurko", "bedside", "kierunkowe"},
    "reading": {"czytanie", "biurko", "bedside", "focused", "directional"},
    "sypialni": {"sypialnia", "bedroom", "nocna", "bedside", "cieple", "ambient"},
    "sypialnia": {"bedroom", "nocna", "bedside", "cieple", "ambient"},
    "bedroom": {"sypialnia", "nocna", "bedside", "cieple", "ambient"},
    "lozko": {"lozku", "bed", "bedside", "nocna", "czytanie", "sypialnia"},
    "lozka": {"lozko", "bed", "bedside", "nocna", "czytanie", "sypialnia"},
    "lozku": {"lozko", "bed", "bedside", "nocna", "czytanie", "sypialnia"},
    "bed": {"lozko", "lozku", "bedside", "night", "reading", "bedroom"},
    "nocna": {"nocne", "night", "bedside", "sypialnia", "ambient"},
    "nocne": {"nocna", "night", "bedside", "sypialnia", "ambient"},
    "night": {"nocna", "nocne", "bedside", "bedroom", "ambient"},
    "wisząca": {"wisiaca", "wiszaca", "pendant", "ceiling", "sufit", "zwis"},
    "wiszaca": {"wisiaca", "pendant", "ceiling", "sufit", "zwis"},
    "wisiaca": {"wiszaca", "pendant", "ceiling", "sufit", "zwis"},
    "pendant": {"wiszaca", "wisiaca", "ceiling", "sufit", "zwis"},
    "sufitowa": {"sufit", "ceiling", "plafon", "wiszaca", "pendant"},
    "sufitowe": {"sufit", "ceiling", "plafon", "wiszaca", "pendant"},
    "ceiling": {"sufit", "sufitowa", "plafon", "pendant", "wiszaca"},
    "podlogowa": {"podloga", "floor", "standing", "stojaca", "wysoka"},
    "podlogowe": {"podloga", "floor", "standing", "stojaca", "wysoka"},
    "floor": {"podlogowa", "podloga", "standing", "stojaca", "tall"},
    "stojaca": {"podlogowa", "floor", "standing", "wysoka"},
    "kinkiet": {"scienny", "wall", "sconce", "korytarz", "lazienka"},
    "kinkiety": {"scienny", "wall", "sconce", "korytarz", "lazienka"},
    "scienna": {"kinkiet", "wall", "sconce"},
    "scienne": {"kinkiet", "wall", "sconce"},
    "wall": {"kinkiet", "scienny", "sconce"},
    "sconce": {"kinkiet", "scienny", "wall"},
    "reflektor": {"spot", "spotlight", "kierunkowe", "szynowy", "loft"},
    "reflektory": {"spot", "spotlight", "kierunkowe", "szynowy", "loft"},
    "spot": {"reflektor", "spotlight", "directional", "track"},
    "spotlight": {"reflektor", "spot", "directional", "track"},
    "boho": {"rattan", "bambus", "juta", "makrama", "pleciona", "naturalna"},
    "naturalna": {"boho", "rattan", "bambus", "juta", "drewno", "papier"},
    "naturalne": {"boho", "rattan", "bambus", "juta", "drewno", "papier"},
    "industrialna": {"industrial", "loft", "metal", "klatka", "rura", "steampunk"},
    "industrialne": {"industrial", "loft", "metal", "klatka", "rura", "steampunk"},
    "loftowa": {"industrial", "loft", "metal", "klatka", "rura"},
    "loftowe": {"industrial", "loft", "metal", "klatka", "rura"},
    "elegancka": {"premium", "glamour", "krysztal", "mosiadz", "marmur", "luksus"},
    "eleganckie": {"premium", "glamour", "krysztal", "mosiadz", "marmur", "luksus"},
    "luxury": {"premium", "glamour", "crystal", "brass", "marble"},
    "premium": {"glamour", "elegancka", "krysztal", "mosiadz", "marmur", "luxury"},
    "ogrod": {"garden", "outdoor", "solar", "taras", "patio"},
    "ogrodu": {"garden", "outdoor", "solar", "taras", "patio"},
    "garden": {"ogrod", "outdoor", "solar", "taras", "patio"},
    "taras": {"patio", "outdoor", "garden", "solar", "ogrod"},
    "patio": {"taras", "outdoor", "garden", "solar", "ogrod"},
    "dziecka": {"dziecieca", "kids", "children", "nocna", "cloud"},
    "dziecieca": {"dziecka", "kids", "children", "nocna", "cloud"},
    "kids": {"dziecieca", "children", "cloud", "night"},
    "children": {"dziecieca", "kids", "cloud", "night"},
    "nad": {"wiszaca", "wisiaca", "pendant", "ceiling", "sufit", "over"},
    "over": {"nad", "pendant", "ceiling", "sufit", "wiszaca"},
    "stol": {"table", "dining", "jadalnia", "kitchen"},
    "stolem": {"table", "dining", "jadalnia", "kitchen", "pendant", "ceiling"},
    "wyspa": {"island", "kitchen", "pendant", "ceiling", "wiszaca"},
    "island": {"wyspa", "kitchen", "pendant", "ceiling", "wiszaca"},
}


WHITE_LIGHT_QUERY_TERMS = {
    "bathroom",
    "biala",
    "biale",
    "bialy",
    "bialym",
    "clear",
    "cold",
    "cool",
    "default",
    "domyslna",
    "domyslne",
    "jasna",
    "jasne",
    "jasny",
    "klasyczna",
    "klasyczne",
    "neutral",
    "neutralna",
    "neutralne",
    "neutralny",
    "normalna",
    "normalne",
    "restroom",
    "standardowa",
    "standardowe",
    "toilet",
    "washroom",
    "white",
    "zimna",
    "zimne",
    "zwykla",
    "zwykle",
}

WARM_LIGHT_QUERY_TERMS = {
    "amber",
    "ambient",
    "ciepla",
    "cieple",
    "cieply",
    "cozy",
    "golden",
    "nastrojowa",
    "nastrojowe",
    "przytulna",
    "przytulne",
    "warm",
    "yellow",
    "zolta",
    "zolte",
    "zolty",
}

WHITE_PRODUCT_MARKERS = {
    "bial",
    "bathroom",
    "clear",
    "daylight",
    "lazien",
    "lustra",
    "lustro",
    "mirror",
    "neutral",
    "plafon",
    "restroom",
    "toilet",
    "washroom",
    "white",
    "zimn",
}

BATHROOM_QUERY_TERMS = {
    "bathroom",
    "lazienka",
    "lazienki",
    "lustro",
    "mirror",
    "restroom",
    "toilet",
    "washroom",
}

OVER_TABLE_QUERY_TERMS = {
    "dining",
    "island",
    "jadalnia",
    "kitchen",
    "kuchnia",
    "kuchni",
    "nad",
    "over",
    "stol",
    "stolem",
    "wyspa",
}

OVER_TABLE_PRODUCT_MARKERS = {
    "bar",
    "ceiling",
    "chandelier",
    "dining",
    "jadal",
    "kitchen",
    "kuch",
    "linear",
    "listwa",
    "pendant",
    "sufit",
    "wisz",
    "wyspa",
    "zwis",
    "zyrandol",
}

TABLE_LAMP_PRODUCT_MARKERS = {
    "bedside",
    "biurk",
    "desk",
    "nocn",
    "stolowa",
    "table lamp",
}

BED_READING_PRODUCT_MARKERS = {
    "bed",
    "bedhead",
    "bedside",
    "hotelowy",
    "lozk",
    "lozko",
    "nocn",
    "sypial",
}

DESK_ONLY_PRODUCT_MARKERS = {
    "biurk",
    "desk",
    "laptop",
    "lupa",
    "monitor",
    "office",
    "precyzyj",
    "usb",
}

BATHROOM_PRODUCT_MARKERS = {
    "bathroom",
    "ceiling",
    "kinkiet",
    "lazien",
    "lustra",
    "lustro",
    "mirror",
    "plafon",
    "sconce",
    "scienn",
    "sufit",
    "wall",
}

BATHROOM_PRIMARY_MARKERS = {
    "ceiling",
    "flushmount",
    "kinkiet",
    "lustra",
    "lustro",
    "mirror",
    "plafon",
    "sconce",
}

BATHROOM_STRONG_PRODUCT_MARKERS = {
    "flushmount",
    "kinkiet",
    "lustra",
    "lustro",
    "mirror",
    "plafon",
    "sconce",
    "wall",
}

BATHROOM_WHITE_PRIMARY_MARKERS = {
    "ceiling",
    "flushmount",
    "jasn",
    "lustra",
    "lustro",
    "mirror",
    "neutral",
    "plafon",
    "sufit",
    "white",
}

BATHROOM_WARM_DECORATIVE_MARKERS = {
    "amber",
    "bursztyn",
    "ciepl",
    "cozy",
    "gold",
    "miod",
    "nastroj",
    "przytul",
    "warm",
    "zloc",
}

BATHROOM_MISMATCH_MARKERS = {
    "bamboo",
    "bambus",
    "boho",
    "garden",
    "ogrod",
    "outdoor",
    "patio",
    "rattan",
    "solar",
    "taras",
}

NON_BATHROOM_TASK_MARKERS = {
    "bar",
    "bedside",
    "biurk",
    "desk",
    "gaming",
    "grzybek",
    "monitor",
    "mushroom",
    "nocn",
    "podlozk",
    "stol",
    "stolow",
    "table",
    "underbed",
}

SOFT_DECORATIVE_PRODUCT_MARKERS = {
    "accent",
    "akcent",
    "ambient",
    "ambientow",
    "amber",
    "bedside",
    "brass",
    "cage",
    "ceramic",
    "ciepl",
    "cloud",
    "comfort",
    "cozy",
    "crystal",
    "decor",
    "decorative",
    "dziecie",
    "edison",
    "elegan",
    "evening",
    "filament",
    "globe",
    "golden",
    "industrial",
    "kids",
    "klatk",
    "krysztal",
    "lantern",
    "loft",
    "lukow",
    "miek",
    "mood",
    "mosiez",
    "nastroj",
    "night",
    "nocn",
    "premium",
    "przytul",
    "rattan",
    "relaxed",
    "reflektor",
    "soft warm",
    "sofa",
    "spotlight",
    "szyn",
    "warm",
    "wieczor",
    "yellow",
    "zolt",
}

SEMANTIC_PRODUCT_PROFILES = (
    (
        {
            "app",
            "aplikacja",
            "aplikacji",
            "colorful",
            "inteligentna",
            "inteligentne",
            "kolorowa",
            "kolorowe",
            "magia",
            "magiczna",
            "magiczne",
            "magic",
            "magical",
            "phone",
            "rainbow",
            "smart",
            "teczowa",
            "teczowe",
            "telefon",
            "wifi",
        },
        {
            "aplik",
            "aura",
            "barw",
            "czujnik",
            "galaktyk",
            "gradient",
            "gwiazd",
            "kolor",
            "led",
            "lightbar",
            "magicz",
            "motion",
            "neon",
            "piask",
            "projektor",
            "rgb",
            "rgbw",
            "smart",
            "sterowanie",
            "sunset",
            "telefon",
            "wifi",
        },
        78,
    ),
    (
        {"okragla", "okragle", "round", "kula", "kulka", "kulista", "globe", "sphere", "ball"},
        {"globe", "halo", "kula", "kul", "okrąg", "okrag", "pierścien", "pierscien", "ring", "sphere"},
        68,
    ),
    (
        {"pierscien", "pierścien", "ring", "halo"},
        {"halo", "led", "pierścien", "pierscien", "ring"},
        72,
    ),
    (
        {"biurko", "biurka", "biurkowa", "desk", "office", "praca", "study", "work"},
        {"biurk", "desk", "gabinet", "kreśl", "kresl", "lupa", "monitor", "office", "praca", "study", "usb", "work"},
        76,
    ),
    (
        {"czytanie", "czytania", "reading", "ksiazka", "ksiazki", "book", "focused", "skupione"},
        {"bankier", "bedside", "czyt", "desk", "elastycz", "focused", "kierunk", "lupa", "reading", "spot"},
        72,
    ),
    (
        {"sypialnia", "sypialni", "bedroom", "bedside", "nocna", "nocne", "night"},
        {"bedside", "chmur", "ciepl", "dim", "dotyk", "noc", "przytul", "sypial", "warm"},
        74,
    ),
    (
        {"lazienka", "lazienki", "bathroom", "restroom", "toilet", "washroom", "lustro", "mirror"},
        {"ceiling", "flushmount", "kinkiet", "lazien", "lustro", "mirror", "plafon", "sconce", "sufit", "wall"},
        92,
    ),
    (
        {"kuchnia", "kuchni", "kitchen", "jadalnia", "jadalni", "dining", "island", "wyspa", "stol", "stolem"},
        {"bar", "dining", "jadal", "kitchen", "kuch", "linear", "listwa", "pendant", "stol", "wisz", "wyspa"},
        76,
    ),
    (
        {"salon", "living", "lounge", "sofa", "kanapa"},
        {"arc", "dekor", "floor", "glamour", "lounge", "luk", "podlog", "salon", "sofa", "statement"},
        66,
    ),
    (
        {"wiszaca", "wisząca", "wisiaca", "pendant", "zwis", "sufitowa", "sufitowe", "ceiling", "zyrandol"},
        {"ceiling", "chandelier", "flushmount", "pendant", "plafon", "sufit", "wisz", "zwis", "zyrandol"},
        76,
    ),
    (
        {"podlogowa", "podlogowe", "podloga", "floor", "standing", "stojaca", "wysoka", "tall"},
        {"floor", "podlog", "standing", "stoj", "tall", "tripod", "wysok"},
        76,
    ),
    (
        {"kinkiet", "kinkiety", "scienna", "scienne", "wall", "sconce"},
        {"kinkiet", "scien", "sconce", "wall"},
        82,
    ),
    (
        {"reflektor", "reflektory", "spot", "spotlight", "szyna", "szynowy", "track", "kierunkowe"},
        {"directional", "kierunk", "reflektor", "spot", "spotlight", "szyn", "track"},
        82,
    ),
    (
        {"boho", "naturalna", "naturalne", "rattan", "bambus", "juta", "makrama", "papier", "pleciona", "woven"},
        {"bamboo", "bambus", "boho", "jute", "juta", "makram", "natural", "papier", "plecion", "rattan", "seagrass", "trawy", "woven"},
        78,
    ),
    (
        {"industrial", "industrialna", "industrialne", "loft", "loftowa", "loftowe", "metal", "rura", "steampunk", "klatka"},
        {"cage", "gear", "industrial", "klatk", "loft", "metal", "pipe", "pulley", "rur", "spotlight", "steampunk", "zebat"},
        78,
    ),
    (
        {"elegancka", "eleganckie", "glamour", "luksus", "luksusowa", "luxury", "premium", "krysztal", "crystal"},
        {"brass", "crystal", "diament", "elegan", "glamour", "gold", "krysztal", "luksus", "marble", "marmur", "mosiadz", "premium"},
        74,
    ),
    (
        {"retro", "vintage", "klasyczna", "klasyczne", "stara", "stare", "70s", "bankierska", "tiffany"},
        {"70", "art deco", "bankier", "classic", "klasy", "retro", "space age", "tiffany", "vintage", "witra"},
        66,
    ),
    (
        {"ogrod", "ogrodu", "garden", "outdoor", "zewnatrz", "taras", "patio", "solar", "solarna"},
        {"garden", "ogrod", "outdoor", "patio", "solar", "slup", "taras", "zewn"},
        82,
    ),
    (
        {"dziecka", "dziecieca", "dzieci", "kids", "children", "child", "cloud", "chmurka"},
        {"children", "chmur", "cloud", "dzieci", "kids", "noc"},
        80,
    ),
    (
        {"mala", "male", "niewielka", "compact", "small", "przenosna", "portable", "bezprzewodowa", "wireless"},
        {"akumulator", "bar", "bezprzew", "clip", "compact", "dotyk", "klips", "lantern", "lataren", "portable", "przenos", "rechargeable", "usb", "wireless"},
        62,
    ),
    (
        {"czarna", "czarne", "black", "minimal", "minimalistyczna", "minimalistyczne", "prosta", "simple"},
        {"black", "czarn", "kreska", "linear", "minimal", "proste", "slim", "smuk"},
        58,
    ),
    (
        {"ciepla", "cieple", "cieply", "zolta", "zolte", "zolty", "amber", "bursztyn", "miodowa", "cozy", "warm"},
        {"amber", "bursztyn", "ciepl", "cozy", "golden", "honey", "miod", "nastroj", "przytul", "sunset", "warm", "zolt"},
        58,
    ),
    (
        {"biala", "biale", "bialy", "neutralna", "neutralne", "white", "clear", "jasna", "jasne"},
        {"bial", "ceiling", "clear", "flushmount", "jasn", "led", "neutral", "plafon", "white"},
        56,
    ),
)

PRODUCT_KEYWORD_PROFILES = (
    (
        {"rgb", "smart", "wifi", "neon", "galaktyk", "gwiazd", "sunset", "aura", "projektor", "piask"},
        {"smart", "rgb", "kolorowe", "teczowe", "magiczne", "nastrojowe", "colorful", "rainbow", "magic"},
    ),
    (
        {"globe", "kula", "halo", "ring", "pierścien", "pierscien"},
        {"okragle", "kuliste", "round", "sphere", "globe"},
    ),
    (
        {"biurk", "desk", "monitor", "usb", "lupa", "kreśl", "kresl"},
        {"biurko", "praca", "czytanie", "desk", "work", "reading"},
    ),
    (
        {"kinkiet", "sconce", "wall", "scienn"},
        {"kinkiet", "scienne", "wall", "sconce"},
    ),
    (
        {"pendant", "wiszaca", "wisząca", "sufit", "ceiling", "plafon", "zyrandol"},
        {"wiszace", "sufitowe", "pendant", "ceiling"},
    ),
    (
        {"podlog", "floor", "standing", "stoj"},
        {"podlogowe", "stojace", "floor", "standing"},
    ),
    (
        {"boho", "rattan", "bambus", "juta", "makram", "papier", "seagrass"},
        {"boho", "naturalne", "plecione", "natural", "woven"},
    ),
    (
        {"industrial", "loft", "metal", "pipe", "pulley", "gear", "klatk", "rur"},
        {"industrialne", "loftowe", "metalowe", "steampunk", "loft"},
    ),
    (
        {"crystal", "krysztal", "glamour", "marmur", "marble", "mosiadz", "brass"},
        {"premium", "glamour", "eleganckie", "luksusowe", "luxury"},
    ),
    (
        {"solar", "garden", "ogrod", "outdoor", "taras", "patio"},
        {"ogrodowe", "tarasowe", "zewnetrzne", "outdoor", "garden"},
    ),
)


def query_terms(query: str) -> set[str]:
    terms = {
        term
        for term in comparable_text(query).split()
        if len(term) > 2 and term not in STOP_WORDS
    }

    expanded = set(terms)
    for term in terms:
        expanded.update(QUERY_SYNONYMS.get(term, set()))

    return expanded


def semantic_profile_score(terms: set[str], haystack: str) -> int:
    score = 0
    for query_markers, product_markers, boost in SEMANTIC_PRODUCT_PROFILES:
        if not terms & query_markers:
            continue

        marker_matches = sum(1 for marker in product_markers if marker in haystack)
        if marker_matches:
            score += boost + min(marker_matches, 5) * 8

    return score


def derive_product_keywords(*values: str) -> list[str]:
    raw_text = " ".join(value for value in values if value)
    haystack = comparable_text(raw_text)
    keywords = {
        term
        for term in normalize_text(raw_text).split()
        if len(term) > 2 and comparable_text(term) not in STOP_WORDS
    }

    for product_markers, extra_keywords in PRODUCT_KEYWORD_PROFILES:
        if contains_any_marker(haystack, product_markers):
            keywords.update(extra_keywords)

    return sorted(keywords)


def light_preference_for_query(query: str) -> str | None:
    terms = {
        term
        for term in comparable_text(query).split()
        if len(term) > 2 and term not in STOP_WORDS
    }
    wants_white = bool(terms & WHITE_LIGHT_QUERY_TERMS)
    wants_warm = bool(terms & WARM_LIGHT_QUERY_TERMS)

    if wants_white and not wants_warm:
        return "white"
    if wants_warm and not wants_white:
        return "warm"
    return None


def product_text(product: Product) -> str:
    return " ".join(
        [
            comparable_text(product.id),
            comparable_text(product.name),
            comparable_text(product.category),
            comparable_text(product.description),
            comparable_text(" ".join(product.tags)),
            comparable_text(" ".join(product.keywords)),
            comparable_text(" ".join(f"{key} {value}" for key, value in product.attributes.items())),
        ]
    )


def contains_any_marker(text: str, markers: set[str]) -> bool:
    return any(marker in text for marker in markers)


def is_product_allowed_for_light_preference(product: Product, preference: str | None) -> bool:
    if preference not in {"white", "warm"}:
        return True

    haystack = product_text(product)
    has_white_profile = contains_any_marker(haystack, WHITE_PRODUCT_MARKERS)
    has_bathroom_profile = contains_any_marker(haystack, BATHROOM_PRODUCT_MARKERS)
    has_soft_decorative_profile = contains_any_marker(haystack, SOFT_DECORATIVE_PRODUCT_MARKERS)

    if preference == "white":
        return has_bathroom_profile or not has_soft_decorative_profile or has_white_profile

    return has_soft_decorative_profile or not has_white_profile


def is_lamp_query(query: str) -> bool:
    terms = query_terms(query)
    return bool(terms & {"lamp", "lampa", "led", "light", "lighting", "swiatlo"})


def score_product(product: Product, query: str) -> int:
    product_id = comparable_text(product.id)
    name = comparable_text(product.name)
    category = comparable_text(product.category)
    description = comparable_text(product.description)
    tags = comparable_text(" ".join(product.tags))
    keywords = comparable_text(" ".join(product.keywords))
    attributes = comparable_text(" ".join(f"{key} {value}" for key, value in product.attributes.items()))
    haystack = " ".join([product_id, name, category, description, tags, keywords, attributes])
    comparable_query = comparable_text(query)
    light_preference = light_preference_for_query(query)
    terms = query_terms(query)
    wants_bathroom = bool(terms & BATHROOM_QUERY_TERMS)
    wants_over_table = "nad" in terms or "over" in terms or (
        bool(terms & {"wyspa", "island", "stolem"}) and bool(terms & OVER_TABLE_QUERY_TERMS)
    )
    wants_bed_reading = bool(terms & {"bed", "bedside", "lozko", "lozka", "lozku"}) and bool(
        terms & {"book", "czytanie", "czytania", "focused", "ksiazka", "ksiazki", "reading"}
    )

    if wants_bathroom and not contains_any_marker(haystack, BATHROOM_STRONG_PRODUCT_MARKERS):
        return 0

    if not is_product_allowed_for_light_preference(product, light_preference):
        return 0

    if comparable_query in product_id:
        return 100
    if comparable_query in name:
        return 90
    if comparable_query in haystack:
        return 60

    score = 0
    for term in terms:
        if term in product_id:
            score += 35
        if term in name:
            score += 30
        if term in category or term in tags:
            score += 22
        if term in keywords:
            score += 16
        if term in description or term in attributes:
            score += 10

    score += semantic_profile_score(terms, haystack)

    if light_preference == "white" and contains_any_marker(haystack, WHITE_PRODUCT_MARKERS):
        score += 18
    if light_preference == "warm" and contains_any_marker(haystack, SOFT_DECORATIVE_PRODUCT_MARKERS):
        score += 18
    if wants_bathroom:
        if contains_any_marker(haystack, BATHROOM_PRODUCT_MARKERS):
            score += 110
        else:
            score -= 90
        if contains_any_marker(haystack, BATHROOM_PRIMARY_MARKERS):
            score += 80
        if light_preference == "white" and contains_any_marker(haystack, BATHROOM_WHITE_PRIMARY_MARKERS):
            score += 140
        if light_preference == "white" and contains_any_marker(haystack, BATHROOM_WARM_DECORATIVE_MARKERS):
            score -= 75
        if contains_any_marker(haystack, BATHROOM_MISMATCH_MARKERS):
            score -= 90
        if contains_any_marker(haystack, NON_BATHROOM_TASK_MARKERS):
            score -= 60
    if wants_over_table:
        if contains_any_marker(haystack, OVER_TABLE_PRODUCT_MARKERS):
            score += 120
        if contains_any_marker(haystack, TABLE_LAMP_PRODUCT_MARKERS) and not contains_any_marker(haystack, OVER_TABLE_PRODUCT_MARKERS):
            score -= 130
    if wants_bed_reading:
        if contains_any_marker(haystack, BED_READING_PRODUCT_MARKERS):
            score += 135
        if contains_any_marker(haystack, DESK_ONLY_PRODUCT_MARKERS) and not contains_any_marker(haystack, BED_READING_PRODUCT_MARKERS):
            score -= 120

    return score


def map_sql_server_product(row: Any) -> Product:
    keywords = derive_product_keywords(
        str(row.id),
        str(row.name),
        str(row.category or "lamp"),
        str(row.description or ""),
    )
    return Product(
        id=str(row.id),
        name=str(row.name),
        price=float(row.price),
        currency=str(row.currency or "PLN"),
        category=str(row.category or "lamp"),
        description=str(row.description or ""),
        tags=[str(row.category or "lamp")],
        keywords=keywords,
        stock_status=str(row.stock_status or "unknown"),
        image_url=str(row.image_url) if row.image_url else None,
        attributes={
            "category": str(row.category or "lamp"),
            "keywords": ", ".join(keywords[:24]),
        },
    )
