# Architecture Decision Records

Upstream baseline: `langchain-ai/open-swe@ad545353e2cdb4c7ae1c419f966c82436b63e799`。日期：2026-09-28。

当前范围由 [MVP-001 v1.0](../MVP_DEVELOPMENT_PLAN.md) 与 ADR-011 固定。决策状态不表示实现通过验收。当前采用 ADR-007/008，并由 ADR-009/010 细化；旧方案保留作为历史。

| ADR | 状态 |
|---|---|
| [001: Why Open SWE](ADR-001-why-open-swe-as-upstream.md) | 保留；可信本地 Runtime 已验收 |
| [002: Spring + Python](ADR-002-spring-control-plane-python-execution.md) | 已由 007 替代 |
| [003: RabbitMQ](ADR-003-rabbitmq-asynchronous-execution.md) | 已由 008 替代；异步原则保留 |
| [004: Backend vs Agent State](ADR-004-backend-state-vs-agent-state.md) | 保留；存储修订为 PG |
| [005: Sandbox lifecycle/providers](ADR-005-sandbox-lifecycle-provider-strategy.md) | 保留；metadata 修订为 PG |
| [006: Retain Runtime/PostgreSQL](ADR-006-retain-upstream-runtime-postgresql.md) | 部分由 008 替代；双 DB 取消 |
| [007: Python-first Control Plane](ADR-007-python-first-control-plane.md) | 已实现，对应 M0–M5 |
| [008: Infrastructure reuse by capability](ADR-008-reuse-infrastructure-by-capability.md) | 已实现，最小故障契约通过 |
| [009: Independent clean validation](ADR-009-independent-clean-validation.md) | 已实现，独立 PASS/FAIL/ERROR 与接管通过 |
| [010: Dispatch lease/reconciliation](ADR-010-dispatch-lease-reconciliation.md) | 已实现，真实 SDK 对账/worker SIGKILL 通过 |
| [011: Core MVP with basic React UI](ADR-011-mvp-core-scope-basic-ui.md) | M0–M7 本版可信本地范围已验收 |
| [012: Local Repair deployment](ADR-012-reproducible-local-repair-demo.md) | 已实施；真实 build/三服务/新 volumes/Linux tests/browser 通过 |
| [013: Standalone Repair Worker](ADR-013-standalone-repair-worker.md) | 独立 Worker 四服务阶段已验收；后续 Redis Streams 五服务增量见 [验收记录](../architecture/MVP_ACCEPTANCE.md) |
