"""Apply curated Chinese demo copy through the normal merchant approval transaction."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json

from shopmate.auth import AuthClient, RequestIdentity
from shopmate.commerce_client import CommerceClient
from shopmate.sessions import SessionStore
from shopmate.settings import ROOT, Settings

COPY = ROOT / "scripts/data/demo-catalog-zh-CN.json"


async def apply_copy(*, apply: bool, selected: list[str]):
    data = json.loads(COPY.read_text())
    products = data["products"]
    if selected:
        products = {key: products[key] for key in selected}
    if not apply:
        for product_id, value in products.items():
            print(product_id, value["fields"]["title"])
        return

    settings = Settings.load()
    auth, commerce = AuthClient(settings), CommerceClient(settings.commerce_url)
    store = SessionStore(settings.state_path)
    results = []
    output = ROOT / ".run/demo-catalog-localization.json"
    try:
        login = await auth.login(
            "shopmate-fixture-operator", (ROOT / ".run/operator_password").read_text().strip()
        )
        user = RequestIdentity(login["subject"], login["accessToken"])
        binding = store.storefront(user.subject).authorization_id
        for product_id, value in products.items():
            token = await auth.exchange(user, binding, "merchant:read")
            current = await commerce.listing(product_id, token, binding)
            fields = value["fields"]
            if current.title == fields["title"] and all(
                current.shortDescription == desired
                if key == "short_description"
                else current.content.get("longDescription") == desired
                for key, desired in fields.items()
                if key != "title"
            ):
                print(product_id, "already localized")
                continue
            if current.title not in (value["source_title"], fields["title"]):
                print(product_id, "kept existing merchant title")
                continue
            payload = {
                "kind": "LISTING_UPDATE",
                "payload": {"listingId": product_id, "fields": fields},
            }
            version = f"{current.publicationVersion}:{current.metadataVersion}:{current.familyMetadataVersion}"
            key = (
                "demo-copy-"
                + hashlib.sha256(
                    (
                        data["version"] + product_id + version + json.dumps(fields, sort_keys=True)
                    ).encode()
                ).hexdigest()[:40]
            )
            token = await auth.exchange(user, binding, "merchant:change:prepare")
            change = await commerce.prepare(payload, key, token, binding)
            result = await commerce.apply(change.changeId, user.token)
            if result.state != "APPLIED":
                raise RuntimeError(f"{product_id}: approval returned {result.state}")
            results.append(
                {"product_id": product_id, "change_id": result.changeId, "state": result.state}
            )
            output.write_text(
                json.dumps({"copy_version": data["version"], "changes": results}, indent=2) + "\n"
            )
            print(product_id, "localized")
    finally:
        store.close()
        await auth.close()
        await commerce.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Approve the listed demo-copy edits on the configured local services",
    )
    parser.add_argument(
        "--product",
        action="append",
        default=[],
        help="Limit the operation to an explicit demo product ID",
    )
    args = parser.parse_args()
    asyncio.run(apply_copy(apply=args.apply, selected=args.product))


if __name__ == "__main__":
    main()
