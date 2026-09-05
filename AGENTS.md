# Development agreement

- Work on one branch and one pull request at a time. Use the smallest implementation needed for the current product.
- Keep model and service credentials in ignored runtime files. Never commit credentials, private planning, invented results, or personal data.
- Preserve vendored licenses and source notices. Commit as the repository owner without assistant attribution.
- Run relevant Python, TypeScript and integration checks before review. Never weaken existing tests to obtain a pass.
- Use an independent read-only reviewer before merging substantive work. Findings must identify executable behavior, trust-boundary or cleanup problems.
- Record actual model/evaluation results with full source revisions and workload definitions. Use SQL against authoritative business tables for write truth. Do not build proof frameworks around results.
