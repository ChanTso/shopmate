# Contributing to ShopMate

Small, focused fixes to the native apps, merchant workspace, and agent host are welcome. Start with the [project overview](README.md) ([简体中文](README.zh-CN.md)) and the relevant platform guide.

## Set up

Use Python 3.11+, uv, and Node.js 24. From the repository root:

```sh
uv sync --frozen
npm --prefix web ci
```

The [runtime guide](docs/RUNTIME.md#run-locally) covers the sibling CityBuddy checkout, Java 21, Docker Compose, and local service configuration. Native prerequisites and build commands are in the [Android](android/README.md) and [iOS](ios/README.md) guides. The [product site](site/README.md) can be previewed independently.

## Check your changes

Run checks for the areas you change:

| Area | Checks |
|---|---|
| Python host | `uv run ruff check src tests scripts integration_tests`, `uv run ruff format --check src tests scripts integration_tests`, and the application/runtime pytest suite in the [runtime guide](docs/RUNTIME.md#checks-and-historical-records) |
| Merchant Web | `npm --prefix web run typecheck`, `npm --prefix web test`, `npm --prefix web run build` |
| Android / shared Kotlin | `cd android && ./gradlew --no-daemon :shared:jvmTest :app:assembleDebug :app:testDebugUnitTest :app:lintDebug` |
| iOS | Follow the [build and Simulator test commands](ios/README.md) for the affected behavior; the CI build-for-testing step builds test bundles but does not run them |
| Documentation / site | Check relative links and language switches; preview changed layouts at desktop and mobile widths |

[GitHub Actions](.github/workflows/ci.yml) runs the Python, Web, Android, and Apple build checks on pull requests. Preserve existing tests; add regression coverage when a behavior change needs it.

Real Java/database integration tests and real-model evaluations are separate from the checks above. `uv run pytest integration_tests -q` changes demo business data: use the [fixture reset and serial-run instructions](docs/RUNTIME.md#checks-and-historical-records). Read a recorded evaluation's setup before running it; model calls use the configured provider and may incur cost.

## Submit a pull request

- Keep one active branch and PR per contribution. Describe the concrete problem, resulting behavior, and commands you actually ran, including failures or checks you could not run.
- Keep both README languages aligned when their content changes; shared assets and deeper technical documents do not need duplicate copies.
- Follow the existing platform and service boundaries. For a substantial change, obtain an independent review before merging.

## Preserve evidence and attribution

Keep credentials, runtime databases, personal data, and private planning out of commits. Record real evaluation results with workload definitions and full source revisions; use SQL against authoritative business tables for write outcomes. Do not present edited showcase animations as performance measurements.

Preserve vendored licenses, source notices, and image credits. ShopMate remains licensed under [Apache-2.0](LICENSE). Repository maintenance rules are in [AGENTS.md](AGENTS.md).
