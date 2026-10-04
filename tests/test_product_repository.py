from app.domain.models import Product
from types import SimpleNamespace

from app.repositories.product_repository import InMemoryProductRepository, map_sql_server_product


def make_product(
    product_id: str,
    name: str,
    category: str,
    description: str,
    keywords: list[str] | None = None,
    tags: list[str] | None = None,
) -> Product:
    return Product(
        id=product_id,
        name=name,
        price=50.0,
        currency="PLN",
        category=category,
        description=description,
        tags=tags or [category],
        keywords=keywords or [],
        stock_status="in_stock",
        image_url="images/lamp1.jpg",
    )


def test_magic_and_rainbow_query_prefers_rgb_ambient_products():
    repository = InMemoryProductRepository(
        [
            make_product(
                "smart-rgb-desk-ambient-ring",
                "Okrągła lampa biurkowa Halo Smart",
                "Aura biurka",
                "Barwna lampa RGB z kolorowym światłem i efektem halo.",
            ),
            make_product(
                "minimal-table-lamp",
                "Minimalistyczna lampa stołowa",
                "Studyjny blask",
                "Prosta lampka stołowa z ciepłym światłem.",
            ),
        ]
    )

    products = repository.search_products("magiczna tęczowa lampa", limit=2)

    assert [product.id for product in products][0] == "smart-rgb-desk-ambient-ring"


def test_bathroom_white_query_filters_out_desktop_led_lamps():
    repository = InMemoryProductRepository(
        [
            make_product(
                "magnifying-led-desk-lamp",
                "Lampa biurkowa z lupą LED",
                "Precyzyjne prace",
                "Lampa z pierścieniowym światłem LED do prac przy biurku.",
            ),
            make_product(
                "smart-ceiling-flushmount",
                "Sufitowy plafon Smart LED",
                "Główne światło",
                "Płaski natynkowy plafon z regulacją temperatury światła.",
            ),
            make_product(
                "crystal-wall-sconce-pair",
                "Zestaw 2 kinkietów kryształowych",
                "Para glamour",
                "Kinkiety przeznaczone do oprawy lustra.",
            ),
        ]
    )

    product_ids = [product.id for product in repository.search_products("biała lampa do łazienki", limit=5)]

    assert "magnifying-led-desk-lamp" not in product_ids
    assert {"crystal-wall-sconce-pair", "smart-ceiling-flushmount"}.issubset(product_ids)


def test_over_table_query_prefers_pendant_lamps_over_table_lamps():
    repository = InMemoryProductRepository(
        [
            make_product(
                "rattan-table-lamp",
                "Rattanowa lampa stołowa",
                "Naturalna faktura",
                "Mała lampka stołowa z plecionym kloszem.",
            ),
            make_product(
                "opal-pendant-lamp",
                "Lampa wisząca Opal",
                "Jadalnia",
                "Wisząca lampa nad stołem i wyspą kuchenną.",
            ),
        ]
    )

    products = repository.search_products("lampy nad stół do kuchni", limit=2)

    assert [product.id for product in products][0] == "opal-pendant-lamp"


def test_sql_product_mapping_loads_polish_and_english_search_tags():
    row = SimpleNamespace(
        id="green-marble-lamp",
        name="Zielona lampa marmurowa",
        name_en="Green marble lamp",
        price=100,
        currency="PLN",
        category="Lampa stołowa",
        description="Kamienna lampka na biurko.",
        description_en="Stone desk lamp.",
        meta_pl='["ciemnozielony marmur", "lampka stołowa"]',
        meta_en='["dark green marble", "table lamp"]',
        stock_status="in_stock",
        image_url="images/lamp121.jpg",
    )

    product = map_sql_server_product(row)

    assert "ciemnozielony marmur" in product.tags
    assert "dark green marble" in product.tags
    assert "zielona" in product.keywords


def test_physical_green_lamp_ranks_before_rgb_for_plain_color_request():
    repository = InMemoryProductRepository(
        [
            make_product(
                "green-pendant",
                "Zielona lampa wisząca",
                "Lampa wisząca",
                "Metalowy zielony klosz.",
                tags=["zielona emaliowana lampa", "green enamel pendant"],
            ),
            make_product(
                "rgb-floor",
                "Lampa podłogowa RGB",
                "Smart RGB",
                "Lampa sterowana aplikacją.",
                tags=["czerwone zielone niebieskie światło RGB", "app color control"],
            ),
        ]
    )

    products = repository.search_products("zielona lampa", limit=2)

    assert products[0].id == "green-pendant"


def test_rgb_lamp_ranks_first_when_user_asks_for_green_light_capability():
    repository = InMemoryProductRepository(
        [
            make_product(
                "green-pendant",
                "Zielona lampa wisząca",
                "Lampa wisząca",
                "Metalowy zielony klosz.",
                tags=["zielona emaliowana lampa", "green enamel pendant"],
            ),
            make_product(
                "rgb-floor",
                "Lampa podłogowa RGB",
                "Smart RGB",
                "Lampa sterowana aplikacją.",
                tags=["czerwone zielone niebieskie światło RGB", "app color control"],
            ),
        ]
    )

    products = repository.search_products("lampa, która może świecić na zielono", limit=2)

    assert products[0].id == "rgb-floor"


def test_smart_query_excludes_regular_lamps():
    repository = InMemoryProductRepository(
        [
            make_product(
                "regular-night-light",
                "Lampka nocna",
                "Lampka stołowa",
                "Ciepłe światło do pokoju dziecka.",
            ),
            make_product(
                "smart-wifi-light",
                "Lampa Smart WiFi",
                "Smart home",
                "Inteligentna lampa sterowana przez WiFi.",
            ),
        ]
    )

    products = repository.search_products("smart lampa", limit=5)

    assert [product.id for product in products] == ["smart-wifi-light"]
