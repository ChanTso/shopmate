"""Reset the reserved local fixture after task writers have stopped and catalog delivery drained."""

from __future__ import annotations

import re
import time

import local_runtime as runtime


def main() -> None:
    print("citybuddy_commit=" + runtime.run(["git", "rev-parse", "HEAD"], log=False))
    print(
        "shopmate_commit=" + runtime.run(["git", "rev-parse", "HEAD"], cwd=runtime.ROOT, log=False)
    )
    runtime.read_env()
    deadline = time.monotonic() + 90
    while True:
        pending = int(
            runtime.sql(
                "SELECT COUNT(*) FROM commerce_outbox WHERE aggregate_type='PRODUCT' "
                "AND publication_state='PENDING';"
            )
        )
        progress = runtime.compose(
            "run",
            "--rm",
            "--no-deps",
            "rocketmq-admin",
            "consumerProgress",
            "--namesrvAddr",
            "rocketmq-namesrv:9876",
            "--groupName",
            runtime.GROUP,
            "--topic",
            runtime.TOPIC,
        )
        diff = re.search(r"Consume Diff Total:\s*(\d+)", progress)
        inflight = re.search(r"Consume Inflight Total:\s*(\d+)", progress)
        if not diff or not inflight:
            raise RuntimeError("Catalog consumer progress unavailable; fixture was not reset")
        if pending == 0 and int(diff[1]) == 0 and int(inflight[1]) == 0:
            print(progress)
            break
        if time.monotonic() >= deadline:
            raise RuntimeError("Catalog delivery did not drain; fixture was not reset")
        time.sleep(1)
    runtime.seed_business()
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
