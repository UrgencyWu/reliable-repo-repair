# ADR-008: Reuse infrastructure by capability

Upstream baseline: `langchain-ai/open-swe@ad545353e2cdb4c7ae1c419f966c82436b63e799`。日期：2026-09-28。

## Status

Accepted design; reliability contracts pending。替代 [ADR-003](ADR-003-rabbitmq-asynchronous-execution.md) 的默认 RabbitMQ 和 [ADR-006](ADR-006-retain-upstream-runtime-postgresql.md) 的双数据库方案；保留异步执行与原 Runtime/PG 的必要性。

## Context

原 FastAPI 启动和多 feature 已依赖 PostgreSQL 专用 SQL、Alembic；Server 已能异步执行 graph。仅为技术栈列表加入 MySQL/RabbitMQ/Redis，会额外引入跨系统一致性和两层调度。用户要求在业务目标不受影响时最大复用。

## Decision

Phase 1 复用 PG 应用数据设施和 Runtime 调度。Repair 新表与 dispatch intent 同事务创建；dispatcher 用 SDK 执行并观察原 graph。DB claim/unique constraints、最小 lease/token 与未知结果 reconciliation 纳入 Phase 1；Phase 2 扩展 renew/fencing/retry/deadline 故障矩阵，具体见 ADR-010。保留原 Repository 引用和 trace，避免重复用户/repo/tool 全量数据。

MySQL/RabbitMQ/Redis 暂为候选，出现明确能力缺口或专项训练需求再加入；可替换 adapter 不等于预先搭一套通用队列平台。生产 Runtime 自身依赖单独按选定版本/部署验证，不宣称生产无需 Redis 或 queue。

## Consequences

没有分布式事务或 exactly-once 保证。run 已创建而 reference 未存时必须查明原 run，不能盲目重发；SDK correlation/query/指定 id 契约待测，不支持时缩小自动恢复范围并调整设计。原 transcript best-effort 与 checkpoint 不能替代 Repair 状态事务或 Sandbox filesystem。

原始 MySQL/Redis/RabbitMQ 专项验收被延期，未用 native 测试满足：ACK/NACK/confirm/DLQ、Redis lease contention、MySQL EXPLAIN 都没有通过证据。当前查询优化实验目标改为 PG EXPLAIN ANALYZE。若重新选择这些组件，补充对应 ADR 和真实故障实验。

## Validation

PG transaction/unique claim/concurrency、intent 未派发重启、创建结果未知、旧 run 观察、迟到事件、retry/exhausted 与 workspace 恢复；独立持久性 gate 验证 Server 重启。mock adapter 不能替代真实 Runtime 契约。

相关：[目标架构](../ARCHITECTURE.md)、[Phase 1](../architecture/PHASE_1_PLAN.md)、[ROADMAP](../ROADMAP.md)。
