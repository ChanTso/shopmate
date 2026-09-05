#!/usr/bin/env python3
"""Prepare a separate local CityBuddy database and Java services for ShopMate."""

from __future__ import annotations

import argparse
import json
import os
import secrets
import subprocess
import sys
import time
from http.client import RemoteDisconnected
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
CITY = Path(os.environ.get("CITYBUDDY_DIR", ROOT.parent / "citybuddy")).resolve()
RUN = ROOT / ".run"
ENV = RUN / "citybuddy.env"
PROJECT = "shopmate"
JRE = "eclipse-temurin:21.0.8_9-jre-noble@sha256:20e7f7288e1c18eebe8f06a442c9f7183342d9b022d3b9a9677cae2b558ddddd"
SCOPES = ["merchant:read", "merchant:price:prepare", "merchant:price:read", "merchant:price:cancel"]
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
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=os.environ | (env or {}),
    )
    if log:
        output = result.stdout
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
        'catalog:read merchant:session:create merchant:price:apply')
ON DUPLICATE KEY UPDATE state='ACTIVE',permissions=VALUES(permissions);
INSERT INTO auth_login_credential(principal_id,password_hash)
VALUES ('00000000-0000-0000-0000-0000000a0001','{verifier}')
ON DUPLICATE KEY UPDATE password_hash=VALUES(password_hash);
INSERT INTO auth_service_identity(service_id,client_id,credential_hash,state,allowed_scopes)
VALUES ('00000000-0000-0000-0000-0000000a0002','merchant-agent','{digest}',
        'ACTIVE','{" ".join(SCOPES)}')
ON DUPLICATE KEY UPDATE credential_hash=VALUES(credential_hash),state='ACTIVE',
                       allowed_scopes=VALUES(allowed_scopes);
CREATE USER IF NOT EXISTS 'shopmate_analysis'@'%' IDENTIFIED BY '{analysis_password}';
ALTER USER 'shopmate_analysis'@'%' IDENTIFIED BY '{analysis_password}';
REVOKE ALL PRIVILEGES, GRANT OPTION FROM 'shopmate_analysis'@'%';
GRANT SELECT ON commerce_db.merchant_products TO 'shopmate_analysis'@'%';
GRANT SELECT ON commerce_db.merchant_paid_orders TO 'shopmate_analysis'@'%';
GRANT SELECT ON commerce_db.merchant_daily_sales TO 'shopmate_analysis'@'%';
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
        "sql_port": port,
        "sql_password": analysis_password,
        "state_path": str(RUN / "sessions.sqlite3"),
        "as_of": AS_OF + "T00:00:00+00:00",
    }


def seed_business() -> None:
    fixture = run([sys.executable, "scripts/seed_merchant_fixture.py", "--as-of", AS_OF], log=False)
    sql(fixture)


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
    if sql("SELECT COUNT(*) FROM product WHERE product_id='shopmate-fixture-coffee';") == "0":
        seed_business()
    private(RUN / "settings.json", json.dumps(settings, indent=2) + "\n")
    start_java()
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
