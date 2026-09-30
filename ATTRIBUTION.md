# Attribution

Based on [Open SWE](https://github.com/langchain-ai/open-swe) by LangChain and its contributors.

Upstream baseline: `langchain-ai/open-swe@ad545353e2cdb4c7ae1c419f966c82436b63e799`。审查日期：2026-09-28。

This repository retains upstream Git history, Python agent, runtime integration, sandbox providers, GitHub integrations, React dashboard, and upstream tests. The baseline is also tagged `ci-repair-upstream-baseline`; new development uses `feat/ci-repair-backend` and the official remote is named `upstream`.

The original root README is preserved at [UPSTREAM_README.md](docs/upstream-analysis/UPSTREAM_README.md). The upstream [MIT LICENSE](LICENSE) and embedded third-party licenses under `ui/` are retained.

The downstream contribution implements the Python Repair control plane under `agent/repair/`, transactional dispatch intents, the Open SWE adapter, standalone Worker, immutable candidate patches, independent validation, Worker lease recovery, Repair dashboard pages, migrations, related tests, and local Compose deployment. Implementation details are in [models.py](agent/repair/models.py), [dispatch.py](agent/repair/dispatch.py), and [validation.py](agent/repair/validation.py).
