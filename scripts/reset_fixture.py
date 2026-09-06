"""Reset only the reserved retail identities after local writers and delivery have stopped."""

from __future__ import annotations

import local_runtime as runtime


def main() -> None:
    print("citybuddy_commit=" + runtime.run(["git", "rev-parse", "HEAD"], log=False))
    print(
        "shopmate_commit=" + runtime.run(["git", "rev-parse", "HEAD"], cwd=runtime.ROOT, log=False)
    )
    runtime.read_env()
    runtime.reset_business()
    print(
        runtime.sql(
            "SELECT product_id,price_minor,currency,publication_version,stock_quantity,available "
            "FROM product ORDER BY product_id;"
            "SELECT publication_generation FROM catalog_metadata WHERE singleton_id=1;"
            "SELECT COUNT(*) FROM merchant_price_draft "
            "WHERE operator_subject='shopmate-fixture-operator';"
        )
    )


if __name__ == "__main__":
    main()
