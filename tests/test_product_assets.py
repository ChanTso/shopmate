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


async def test_merchant_web_serves_only_built_assets_without_swallowing_api_routes(
    tmp_path, monkeypatch
):
    import shopmate.app as module

    products = tmp_path / "web/public/products"
    products.mkdir(parents=True)
    monkeypatch.setattr(module, "ROOT", tmp_path)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app()), base_url="http://shopmate.test"
    ) as http:
        assert (await http.get("/")).status_code == 503
    dist = tmp_path / "web/dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>Merchant</html>")
    (dist / "assets/app.js").write_text("export {};")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app()), base_url="http://shopmate.test"
    ) as http:
        response = await http.get("/")
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-cache"
        assert "Merchant" in response.text
        assert (await http.get("/assets/app.js")).status_code == 200
        assert (await http.get("/api/not-a-route")).status_code == 404
        assert (await http.get("/buyer")).status_code == 404
        assert (await http.get("/assets/%2e%2e/%2e%2e/.env")).status_code == 404
