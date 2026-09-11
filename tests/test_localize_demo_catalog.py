import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from shopmate.auth import RequestIdentity
from shopmate.sessions import SessionStore
from shopmate.settings import Settings

spec = importlib.util.spec_from_file_location(
    "localize_demo_catalog",
    Path(__file__).resolve().parents[1] / "scripts/localize_demo_catalog.py",
)
localize = importlib.util.module_from_spec(spec)
spec.loader.exec_module(localize)


@pytest.mark.parametrize("login_fails", [False, True])
async def test_localization_preserves_running_conversation(tmp_path, monkeypatch, login_fails):
    settings = Settings(state_path=tmp_path / "sessions.sqlite3")
    store = SessionStore(settings.state_path)
    try:
        binding = store.storefront("operator").authorization_id
        record = store.create("other-buyer", role="buyer")
        record.items = [{"kind": "assistant", "pending": True, "segments": []}]
        store.begin_turn(record)
        before = dict(store.db.execute("SELECT * FROM sessions").fetchone())
        runtime = tmp_path / ".run"
        runtime.mkdir()
        (runtime / "operator_password").write_text("test-password")
        copy = tmp_path / "copy.json"
        copy.write_text(
            '{"version":"test-copy","products":{"AR-1001":{"source_title":"Original",'
            '"fields":{"title":"Localized","short_description":"Short",'
            '"long_description":"Long"}}}}'
        )
        auth = SimpleNamespace(
            login=AsyncMock(return_value={"subject": "operator", "accessToken": "test-token"}),
            exchange=AsyncMock(return_value="test-delegation"),
            close=AsyncMock(),
        )
        if login_fails:
            auth.login.side_effect = HTTPException(401, "Authentication denied")
        commerce = SimpleNamespace(
            listing=AsyncMock(
                return_value=SimpleNamespace(
                    title="Localized", shortDescription="Short", content={"longDescription": "Long"}
                )
            ),
            close=AsyncMock(),
        )
        monkeypatch.setattr(localize, "ROOT", tmp_path)
        monkeypatch.setattr(localize, "COPY", copy)
        monkeypatch.setattr(localize, "Settings", SimpleNamespace(load=lambda: settings))
        monkeypatch.setattr(localize, "AuthClient", lambda settings: auth)
        monkeypatch.setattr(localize, "CommerceClient", lambda url: commerce)

        if login_fails:
            with pytest.raises(HTTPException) as failure:
                await localize.apply_copy(apply=True, selected=["AR-1001"])
            assert failure.value.status_code == 401
            auth.exchange.assert_not_awaited()
        else:
            await localize.apply_copy(apply=True, selected=["AR-1001"])
            auth.exchange.assert_awaited_once_with(
                RequestIdentity("operator", "test-token"), binding, "merchant:read"
            )
            commerce.listing.assert_awaited_once_with("AR-1001", "test-delegation", binding)

        assert dict(store.db.execute("SELECT * FROM sessions").fetchone()) == before
        store.save(record)
        auth.close.assert_awaited_once()
        commerce.close.assert_awaited_once()
    finally:
        store.close()
