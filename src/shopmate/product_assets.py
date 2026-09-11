"""Shared category photos for the explicitly identified demonstration catalog."""

from .settings import ROOT

PRODUCT_IMAGES = frozenset(path.stem for path in (ROOT / "web/public/products").glob("*.webp"))


def image_url(product_id: str, configured: str | None) -> str | None:
    if configured:
        return configured
    return f"/products/{product_id}.webp" if product_id in PRODUCT_IMAGES else None
