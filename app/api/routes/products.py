from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, HTTPException, Query

from app.api.dependencies import get_product_repository
from app.api.schemas import ProductResponse

router = APIRouter(prefix="/products", tags=["products"])


@router.get("", response_model=list[ProductResponse])
def list_products(search: str | None = Query(default=None, min_length=1)) -> list[ProductResponse]:
    repository = get_product_repository()
    products = repository.search_products(search, limit=10) if search else repository.list_products()
    return [ProductResponse.model_validate(asdict(product)) for product in products]


@router.get("/{product_id}", response_model=ProductResponse)
def get_product(product_id: str) -> ProductResponse:
    repository = get_product_repository()
    product = repository.get_product(product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found.")
    return ProductResponse.model_validate(asdict(product))
