from app.domain.models import Product
from app.repositories.product_repository import InMemoryProductRepository


def make_product(
    product_id: str,
    name: str,
    category: str,
    description: str,
    keywords: list[str] | None = None,
) -> Product:
    return Product(
        id=product_id,
        name=name,
        price=50.0,
        currency="PLN",
        category=category,
        description=description,
        tags=[category],
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
