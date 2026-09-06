#!/usr/bin/env python3
"""Prepare a separate local CityBuddy database and Java services for ShopMate."""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import socket
import sqlite3
import subprocess
import sys
import time
from datetime import UTC, date, datetime
from http.client import RemoteDisconnected
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

import retail_fixture as retail

ROOT = Path(__file__).resolve().parents[1]
CITY = Path(os.environ.get("CITYBUDDY_DIR", ROOT.parent / "citybuddy")).resolve()
RUN = ROOT / ".run"
ENV = RUN / "citybuddy.env"
PROJECT = "shopmate"
JRE = "eclipse-temurin:21.0.8_9-jre-noble@sha256:20e7f7288e1c18eebe8f06a442c9f7183342d9b022d3b9a9677cae2b558ddddd"
MERCHANT_SCOPES = [
    "merchant:read",
    "merchant:price:prepare",
    "merchant:price:read",
    "merchant:price:cancel",
    "merchant:change:prepare",
    "merchant:change:read",
    "merchant:change:cancel",
]
SHOPPING_SCOPES = [
    "shopping:orders:read",
    "shopping:cart:read",
    "shopping:cart:write",
    "shopping:profile:read",
    "refund:create",
]
SCOPES = MERCHANT_SCOPES + SHOPPING_SCOPES
SUBJECT = "shopmate-fixture-operator"
TOPIC = "shopmate-catalog"
GROUP = "shopmate-catalog-consumer"
AS_OF = "2026-09-05"
redactions: set[str] = set()


def private(path: Path, value: str) -> None:
    path.write_text(value)
    path.chmod(0o600)


def read_env() -> dict[str, str]:
    values = dict(
        line.split("=", 1)
        for line in ENV.read_text().splitlines()
        if line and not line.startswith("#") and "=" in line
    )
    redactions.update(values.values())
    return values


def run(
    args: list[str],
    *,
    stdin: str | None = None,
    env: dict | None = None,
    cwd: Path = CITY,
    label: str | None = None,
    log: bool = True,
) -> str:
    if label:
        print(label, flush=True)
    result = subprocess.run(
        args,
        cwd=cwd,
        input=stdin,
        text=True,
        check=False,
        capture_output=True,
        env=os.environ | (env or {}),
    )
    if log:
        output = result.stdout + result.stderr
        for secret in sorted(redactions, key=len, reverse=True):
            if secret:
                output = output.replace(secret, "[REDACTED]")
        with (RUN / "runtime.log").open("a") as stream:
            stream.write((label or args[0]) + "\n" + output + "\n")
    if result.returncode:
        raise RuntimeError(f"{label or args[0]} failed; see .run/runtime.log")
    return result.stdout.strip()


def compose(*args: str, **kwargs) -> str:
    kwargs["env"] = read_env() | kwargs.get("env", {})
    return run(
        [
            "docker",
            "compose",
            "--project-name",
            PROJECT,
            "--env-file",
            str(ENV),
            "--file",
            str(CITY / "compose.yaml"),
            *args,
        ],
        **kwargs,
    )


def make(target: str) -> None:
    run(["make", f"ENV_FILE={ENV}", f"COMPOSE_PROJECT_NAME={PROJECT}", target], label=target)


def sql(statement: str) -> str:
    password = read_env()["MYSQL_BOOTSTRAP_PASSWORD"]
    return run(
        [
            "docker",
            "exec",
            "--interactive",
            "--env",
            "MYSQL_PWD",
            "shopmate-mysql-1",
            "mysql",
            "--user=root",
            "--database=commerce_db",
            "--batch",
            "--skip-column-names",
        ],
        stdin="SET time_zone='+00:00';\n" + statement,
        env={"MYSQL_PWD": password},
        log=False,
    )


def generated(name: str, prefix: str = "") -> str:
    path = RUN / name
    if not path.exists():
        private(path, prefix + secrets.token_hex(32))
    value = path.read_text().strip()
    redactions.add(value)
    return value


def seed_identity() -> dict:
    login_password = generated("operator_password", "sm-")
    merchant_secret = generated("merchant_service_secret", "cbsvc_v1_")
    analysis_password = generated("analysis_password")
    verifier = run(
        [
            "uv",
            "run",
            "python",
            "-c",
            (
                "import bcrypt,sys; print(bcrypt.hashpw(sys.stdin.buffer.read(), "
                "bcrypt.gensalt(rounds=12)).decode())"
            ),
        ],
        stdin=login_password,
        log=False,
    )
    digest = run(
        [sys.executable, "scripts/service_credential.py", "hash", "merchant-agent"],
        stdin=merchant_secret,
        log=False,
    )
    if not (RUN / "auth-private.pem").exists():
        run(
            [
                "openssl",
                "genpkey",
                "-algorithm",
                "RSA",
                "-pkeyopt",
                "rsa_keygen_bits:2048",
                "-out",
                str(RUN / "auth-private.pem"),
            ],
            log=False,
        )
    run(
        [
            "openssl",
            "pkey",
            "-in",
            str(RUN / "auth-private.pem"),
            "-pubout",
            "-out",
            str(RUN / "auth-public.pem"),
        ],
        log=False,
    )
    sql(f"""
INSERT INTO auth_signing_key_metadata(kid,state,activated_at)
VALUES ('shopmate-current','CURRENT',CURRENT_TIMESTAMP(6))
ON DUPLICATE KEY UPDATE state='CURRENT';
INSERT INTO auth_user_principal(principal_id,subject,login_identifier,state,permissions)
VALUES ('00000000-0000-0000-0000-0000000a0001','{SUBJECT}','{SUBJECT}','ACTIVE',
        'catalog:read merchant:session:create merchant:price:apply merchant:change:apply')
ON DUPLICATE KEY UPDATE state='ACTIVE',permissions=VALUES(permissions);
INSERT INTO auth_login_credential(principal_id,password_hash)
VALUES ('00000000-0000-0000-0000-0000000a0001','{verifier}')
ON DUPLICATE KEY UPDATE password_hash=VALUES(password_hash);
INSERT INTO auth_service_identity(service_id,client_id,credential_hash,state,allowed_scopes)
VALUES ('00000000-0000-0000-0000-0000000a0002','merchant-agent','{digest}',
        'ACTIVE','{" ".join(MERCHANT_SCOPES)}')
ON DUPLICATE KEY UPDATE credential_hash=VALUES(credential_hash),state='ACTIVE',
                       allowed_scopes=VALUES(allowed_scopes);
CREATE USER IF NOT EXISTS 'shopmate_analysis'@'%' IDENTIFIED BY '{analysis_password}';
ALTER USER 'shopmate_analysis'@'%' IDENTIFIED BY '{analysis_password}';
REVOKE ALL PRIVILEGES, GRANT OPTION FROM 'shopmate_analysis'@'%';
GRANT SELECT ON commerce_db.merchant_products TO 'shopmate_analysis'@'%';
GRANT SELECT ON commerce_db.merchant_paid_orders TO 'shopmate_analysis'@'%';
GRANT SELECT ON commerce_db.merchant_daily_sales TO 'shopmate_analysis'@'%';
GRANT SELECT ON commerce_db.merchant_listing_facts TO 'shopmate_analysis'@'%';
GRANT SELECT ON commerce_db.merchant_store_traffic_daily TO 'shopmate_analysis'@'%';
GRANT SELECT ON commerce_db.merchant_campaign_facts TO 'shopmate_analysis'@'%';
""")
    shopping_secret = generated("shopping_service_secret", "cbsvc_v1_")
    shopping_digest = run(
        [sys.executable, "scripts/service_credential.py", "hash", "shopping-agent"],
        stdin=shopping_secret,
        log=False,
    )
    sql(f"""
INSERT INTO auth_service_identity(service_id,client_id,credential_hash,state,allowed_scopes)
VALUES ('00000000-0000-0000-0000-0000000a0003','shopping-agent','{shopping_digest}',
        'ACTIVE','{" ".join(SHOPPING_SCOPES)}')
ON DUPLICATE KEY UPDATE credential_hash=VALUES(credential_hash),state='ACTIVE',
                       allowed_scopes=VALUES(allowed_scopes);
""")
    for index, buyer in enumerate(retail.BUYERS):
        password = generated(f"buyer_{index + 1}_password", "sm-")
        verifier = run(
            [
                "uv",
                "run",
                "python",
                "-c",
                "import bcrypt,sys; print(bcrypt.hashpw(sys.stdin.buffer.read(), bcrypt.gensalt(rounds=12)).decode())",
            ],
            stdin=password,
            log=False,
        )
        principal = retail.identity("principal/" + buyer)
        sql(f"""
INSERT INTO auth_user_principal(principal_id,subject,login_identifier,state,permissions)
VALUES ('{principal}','{buyer}','{buyer}','ACTIVE',
        'catalog:read shopping:session:create order:create payment:create')
ON DUPLICATE KEY UPDATE state='ACTIVE',permissions=VALUES(permissions);
INSERT INTO auth_login_credential(principal_id,password_hash)
VALUES ('{principal}','{verifier}')
ON DUPLICATE KEY UPDATE password_hash=VALUES(password_hash);
""")
    port = int(compose("port", "mysql", "3306").rsplit(":", 1)[1])
    truth_password = generated("truth_password")
    tables = (
        "product",
        "seckill_activity",
        "standard_order",
        "seckill_order",
        "mock_payment_attempt",
        "mock_payment_callback",
        "inventory_ledger",
        "merchant_price_draft",
        "commerce_outbox",
        "catalog_metadata",
        "merchant_products",
        "merchant_paid_orders",
        "merchant_daily_sales",
        "merchant_listing_facts",
        "merchant_store_traffic_daily",
        "merchant_campaign_facts",
        "retail_product_family",
        "retail_product_metadata",
        "retail_product_operations",
        "retail_store_traffic_daily",
        "retail_campaign",
        "retail_promotion",
        "retail_promotion_item",
        "retail_order_fulfillment",
        "retail_order_issue",
        "retail_fulfillment_config",
        "shopping_cart",
        "shopping_cart_item",
        "shopping_cart_command",
        "shopping_checkout",
        "shopping_checkout_order",
        "pending_action",
        "action_receipt",
        "mock_refund",
        "faq_source",
    )
    sql(
        f"CREATE USER IF NOT EXISTS 'shopmate_truth'@'%' IDENTIFIED BY '{truth_password}';"
        f"ALTER USER 'shopmate_truth'@'%' IDENTIFIED BY '{truth_password}';"
        "REVOKE ALL PRIVILEGES, GRANT OPTION FROM 'shopmate_truth'@'%';"
        + "\n".join(
            f"GRANT SELECT ON commerce_db.{table} TO 'shopmate_truth'@'%';" for table in tables
        )
    )
    private(
        RUN / "truth-settings.json",
        json.dumps(
            {
                "sql_host": "127.0.0.1",
                "sql_port": port,
                "sql_user": "shopmate_truth",
                "sql_password": truth_password,
                "sql_database": "commerce_db",
            },
            indent=2,
        )
        + "\n",
    )
    return {
        "citybuddy_dir": str(CITY),
        "auth_url": "http://127.0.0.1:9081",
        "commerce_url": "http://127.0.0.1:9082",
        "jwks_url": "http://127.0.0.1:9081/auth/jwks",
        "merchant_service_secret": merchant_secret,
        "shopping_service_secret": shopping_secret,
        "payment_callback_secret": generated("payment_callback_secret"),
        "sql_port": port,
        "sql_password": analysis_password,
        "state_path": str(RUN / "sessions.sqlite3"),
        "as_of": AS_OF + "T00:00:00+08:00",
    }


def require_api_stopped() -> None:
    # The single local host owns action retries; maintenance must not race its writers.
    with socket.socket() as connection:
        connection.settimeout(1)
        if connection.connect_ex(("127.0.0.1", 8101)) == 0:
            raise RuntimeError("Stop the ShopMate API on port 8101 before local maintenance")


def wait_catalog_drained() -> None:
    deadline = time.monotonic() + 90
    while True:
        pending = int(
            sql(
                "SELECT COUNT(*) FROM commerce_outbox WHERE aggregate_type='PRODUCT' "
                "AND publication_state='PENDING';"
            )
        )
        progress = compose(
            "run",
            "--rm",
            "--no-deps",
            "rocketmq-admin",
            "consumerProgress",
            "--namesrvAddr",
            "rocketmq-namesrv:9876",
            "--groupName",
            GROUP,
            "--topic",
            TOPIC,
        )
        diff = re.search(r"Consume Diff Total:\s*(\d+)", progress)
        inflight = re.search(r"Consume Inflight Total:\s*(\d+)", progress)
        if not diff or not inflight:
            raise RuntimeError("Catalog consumer progress unavailable; fixture was not reset")
        if pending == 0 and int(diff[1]) == 0 and int(inflight[1]) == 0:
            return
        if time.monotonic() >= deadline:
            raise RuntimeError("Catalog delivery did not drain; fixture was not reset")
        time.sleep(1)


def reset_fixture_sessions() -> None:
    path = RUN / "sessions.sqlite3"
    if not path.exists():
        return
    backup_dir = RUN / "backups"
    backup_dir.mkdir(mode=0o700, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
    with (
        sqlite3.connect(path) as db,
        sqlite3.connect(backup_dir / f"sessions-{stamp}.sqlite3") as backup,
    ):
        db.backup(backup)
        db.execute("PRAGMA foreign_keys=ON")
        owners = retail.fixture_owners()
        sessions = "SELECT id FROM sessions WHERE owner IN (" + ",".join("?" for _ in owners) + ")"
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "buyer_commands" in tables:
            commands = (
                "SELECT request_key FROM buyer_commands WHERE session_id IN (" + sessions + ")"
            )
            if "buyer_confirmations" in tables:
                db.execute(
                    "DELETE FROM buyer_confirmations WHERE request_key IN (" + commands + ")",
                    owners,
                )
            db.execute("DELETE FROM buyer_commands WHERE session_id IN (" + sessions + ")", owners)
        for table in ("memory_facts", "memory_generations"):
            if table in tables:
                db.execute(
                    "DELETE FROM "
                    + table
                    + " WHERE owner IN ("
                    + ",".join("?" for _ in owners)
                    + ")",
                    owners,
                )
        db.execute("DELETE FROM prepare_intents WHERE session_id IN (" + sessions + ")", owners)
        db.execute("DELETE FROM draft_refs WHERE session_id IN (" + sessions + ")", owners)
        db.execute("DELETE FROM sessions WHERE id IN (" + sessions + ")", owners)


def publish_policies() -> None:
    values = read_env()
    env_file = RUN / "faq-publisher.env"
    private(
        env_file,
        "SPRING_DATASOURCE_URL=jdbc:mysql://mysql:3306/commerce_db?useSSL=false&allowPublicKeyRetrieval=true\n"
        "SPRING_DATASOURCE_USERNAME=commerce_app\n"
        f"SPRING_DATASOURCE_PASSWORD={values['MYSQL_COMMERCE_APP_PASSWORD']}\n",
    )
    jar = CITY / "commerce-service/target/commerce-service-0.0.1-SNAPSHOT.jar"
    run(
        [
            "docker",
            "run",
            "--rm",
            "--interactive",
            "--network",
            "shopmate_default",
            "--env-file",
            str(env_file),
            "--volume",
            f"{jar}:/opt/shopmate/service.jar:ro",
            JRE,
            "java",
            "-Dloader.main=io.citybuddy.commerce.faq.FaqFixturePublisherCli",
            "-cp",
            "/opt/shopmate/service.jar",
            "org.springframework.boot.loader.launch.PropertiesLauncher",
        ],
        stdin=json.dumps(retail.policy_entries(), ensure_ascii=False),
        label="Publish retail policies",
    )


def seed_business() -> None:
    for query in retail.preflight_queries().values():
        if int(sql(query)):
            raise RuntimeError("Fixture products have non-fixture references; maintenance stopped")
    sql(retail.fixture_sql(date.fromisoformat(AS_OF)))
    # SQL and SQLite do not share a transaction; a failure keeps this host unready.
    reset_fixture_sessions()
    publish_policies()


def reset_business() -> None:
    require_api_stopped()
    wait_catalog_drained()
    stop_java()
    seed_business()
    start_java()


def stop_java() -> None:
    names = run(["docker", "ps", "--all", "--format", "{{.Names}}"], log=False).splitlines()
    owned = [name for name in ("shopmate-auth", "shopmate-commerce") if name in names]
    if owned:
        run(["docker", "rm", "--force", *owned], label="Stop ShopMate Java services")


def wait_http(url: str, name: str, expected: int = 200) -> None:
    for _ in range(90):
        try:
            with urlopen(url, timeout=2) as response:
                if response.status == expected:
                    return
        except HTTPError as error:
            if error.code == expected:
                return
        except (URLError, TimeoutError, RemoteDisconnected):
            pass
        state = run(["docker", "inspect", "--format", "{{.State.Running}}", name], log=False)
        if state != "true":
            run(["docker", "logs", "--tail", "80", name], label=name + " startup log")
            raise RuntimeError(name + " stopped during startup")
        time.sleep(1)
    raise RuntimeError(name + " did not become ready")


def start_java() -> None:
    values = read_env()
    for service, account in (("auth", "AUTH"), ("commerce", "COMMERCE")):
        env_values = {"SPRING_DATASOURCE_PASSWORD": values[f"MYSQL_{account}_APP_PASSWORD"]}
        if service == "commerce":
            env_values["SPRING_DATA_REDIS_URL"] = values["COMMERCE_REDIS_URL"]
            env_values["CITYBUDDY_MOCK_PAYMENT_CALLBACK_KEY_ID"] = "shopmate-local-payment"
            env_values["CITYBUDDY_MOCK_PAYMENT_CALLBACK_SECRET"] = generated(
                "payment_callback_secret"
            )
        private(RUN / f"{service}.env", "".join(f"{k}={v}\n" for k, v in env_values.items()))
        jar = CITY / f"{service}-service/target/{service}-service-0.0.1-SNAPSHOT.jar"
        if not jar.is_file():
            raise RuntimeError("Build CityBuddy auth-service and commerce-service JARs first")
        args = [
            "docker",
            "run",
            "--detach",
            "--name",
            f"shopmate-{service}",
            "--network",
            "shopmate_default",
            "--publish",
            f"127.0.0.1:{9081 if service == 'auth' else 9082}:8080",
            "--env-file",
            str(RUN / f"{service}.env"),
            "--volume",
            f"{jar}:/opt/shopmate/service.jar:ro",
        ]
        if service == "auth":
            for kind in ("private", "public"):
                args += ["--volume", f"{RUN}/auth-{kind}.pem:/opt/shopmate/auth-{kind}.pem:ro"]
        else:
            args += ["--cpus", "4"]
        args += [
            JRE,
            "java",
            "-XX:MaxRAMPercentage=70",
            "-jar",
            "/opt/shopmate/service.jar",
            "--server.port=8080",
            "--spring.datasource.url=jdbc:mysql://mysql:3306/commerce_db?useSSL=false&allowPublicKeyRetrieval=true",
            f"--spring.datasource.username={service}_app",
        ]
        if service == "auth":
            args += [
                "--citybuddy.identity.enabled=true",
                "--citybuddy.identity.issuer=https://identity.citybuddy.test",
                "--citybuddy.identity.user-audience=citybuddy-web",
                "--citybuddy.identity.current-kid=shopmate-current",
                "--citybuddy.identity.current-private-key-path=/opt/shopmate/auth-private.pem",
                "--citybuddy.identity.current-public-key-path=/opt/shopmate/auth-public.pem",
            ]
            args += [
                f"--citybuddy.identity.exchange-scopes[{i}]={scope}"
                for i, scope in enumerate(SCOPES)
            ]
        else:
            args += [
                "--citybuddy.catalog.enabled=true",
                "--citybuddy.catalog.issuer=https://identity.citybuddy.test",
                "--citybuddy.catalog.user-audience=citybuddy-web",
                "--citybuddy.catalog.jwks-url=http://shopmate-auth:8080/auth/jwks",
                "--citybuddy.catalog.rocketmq-endpoints=rocketmq-broker-proxy:8081",
                f"--citybuddy.catalog.rocketmq-topic={TOPIC}",
                f"--citybuddy.catalog.rocketmq-consumer-group={GROUP}",
                "--citybuddy.obo.enabled=true",
                "--citybuddy.obo.issuer=https://identity.citybuddy.test",
                "--citybuddy.obo.jwks-url=http://shopmate-auth:8080/auth/jwks",
                "--citybuddy.merchant.enabled=true",
                "--citybuddy.orders.enabled=true",
                "--citybuddy.mock-payment.enabled=true",
                "--citybuddy.refund.enabled=true",
                "--citybuddy.actions.enabled=true",
            ]
        run(args, label=f"Start shopmate-{service}")
        path = "/auth/jwks" if service == "auth" else "/api/products"
        wait_http(
            f"http://127.0.0.1:{9081 if service == 'auth' else 9082}{path}",
            f"shopmate-{service}",
            200 if service == "auth" else 401,
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("up", "stop"))
    args = parser.parse_args()
    os.umask(0o077)
    RUN.mkdir(mode=0o700, exist_ok=True)
    RUN.chmod(0o700)
    if args.action == "stop":
        if ENV.exists():
            read_env()
        stop_java()
        if ENV.exists():
            compose(
                "stop",
                "mysql",
                "redis-commerce",
                "rocketmq-broker-proxy",
                "rocketmq-namesrv",
                label="Stop ShopMate data services; preserve volumes",
            )
        return
    require_api_stopped()
    run(
        ["docker", "build", "--tag", "shopmate-analysis:1", str(ROOT / "infra/analysis-sandbox")],
        cwd=ROOT,
        label="Build isolated analysis image from its dedicated context",
    )
    if not ENV.exists():
        run(
            ["bash", "scripts/init_local.sh"],
            env={"ENV_FILE": str(ENV)},
            label="Create private local database credentials",
        )
    read_env()
    make("rocketmq-store-init")
    compose(
        "up",
        "--detach",
        "--wait",
        "--wait-timeout",
        "180",
        "mysql",
        "redis-commerce",
        "rocketmq-namesrv",
        "rocketmq-broker-proxy",
        label="Start isolated data services",
    )
    for target in (
        "grant-access",
        "migrate-auth",
        "migrate-commerce",
        "migrate-agent",
        "grant-access",
    ):
        make(target)
    for command in (
        ("updateTopic", "--topic", TOPIC, "--readQueueNums", "4", "--writeQueueNums", "4"),
        ("updateSubGroup", "--groupName", GROUP, "--consumeEnable", "true"),
    ):
        compose(
            "run",
            "--rm",
            "--no-deps",
            "rocketmq-admin",
            *command,
            "--namesrvAddr",
            "rocketmq-namesrv:9876",
            "--clusterName",
            "DefaultCluster",
            label=command[0],
        )
    stop_java()
    settings = seed_identity()
    private(RUN / "settings.json", json.dumps(settings, indent=2) + "\n")
    start_java()
    initialized = (
        sql(
            "SELECT EXISTS(SELECT 1 FROM retail_store_traffic_daily WHERE fixture_version="
            + retail.encoded(retail.VERSION)
            + ");"
        )
        == "1"
    )
    if not initialized:
        reset_business()
    else:
        publish_policies()
    print(
        "Java services ready on 9081/9082. Login: shopmate-fixture-operator; password in .run/operator_password."
    )
    print(
        "Start API: uv run uvicorn shopmate.app:create_app --factory --host 127.0.0.1 --port 8101"
    )
    print(
        "Start web: npm --prefix web run dev (port 3100). Model credentials stay in CityBuddy .env."
    )


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1) from None
