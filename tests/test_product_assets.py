import httpx

from shopmate.app import create_app


async def test_native_client_images_share_the_public_catalog_asset_route():
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app()), base_url="http://shopmate.test"
    ) as http:
        image = await http.get("/products/AR-1002.webp")
        assert image.status_code == 200
        assert image.headers["content-type"] == "image/webp"
        assert image.content[:4] == b"RIFF"
        assert (await http.get("/products/%2e%2e/%2e%2e/.env")).status_code == 404
