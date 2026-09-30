# ADR-004: Backend State vs Agent State

Upstream baseline: `langchain-ai/open-swe@ad545353e2cdb4c7ae1c419f966c82436b63e799`。日期：2026-09-28。

## Status

Accepted boundary; transition model proposed。该状态是架构决策状态，不是功能已实现。

## Context

upstreamthread/run/prepare latch/messages与业务RepairTask不是同一生命周期。graphsuccess不等于tests passed，checkpoint不包含一切remote shell副作用或filesystem。

## Decision

2026-09-28 revision：按 ADR-007/008 改用原 PostgreSQL，业务/Agent/Sandbox 权威边界保留。

PostgreSQL存严格enum业务state、RepairRun/attempt、runtime references/events/artifacts；LangGraph存messages/checkpoints/todos/runtime state。PostgreSQL仅投影thread/run/checkpoint/sandboxid，不镜像整个Agentstate。阶段推进来自可验证事件及独立 clean validation；具体身份见执行契约，生成成功不等于验证 PASS。

## Consequences

终态不回退；manualretry终态task生成linked新task。crash恢复同attempt先observe/reconcile原run。跨结果写回与sideeffect窗口不能只靠checkpoint，需fencing与reconcile。完整状态边见docs/ARCHITECTURE.md。

## Validation

单元测试严格边/终态/重复结果；故障测试迟到执行事件/crash/resume；GEThistory保留旧attempt结果，LLM文字不能直接写COMPLETED。

相关：[Upstream审查](../upstream-analysis/OPEN_SWE_ARCHITECTURE.md)、[目标架构](../ARCHITECTURE.md)、[Phase1计划](../architecture/PHASE_1_PLAN.md)。

## Implementation evidence — 2026-09-28

M1 在共享 PostgreSQL 中新增 RepairTask/RepairRun/DispatchIntent/RepairEvent，owner 引用原 users UUID，thread id 在派发前产生。Task/Run/Intent/初始事件同事务，任务验证计划为持久快照；业务 UUID 和 Runtime Run UUID 分开。第一版只使用可确认的 RECEIVED/QUEUED/PROVISIONING/VALIDATING/COMPLETED/FAILED/TIMEOUT，不从模型消息推断诊断节点。非法跨阶段/终态回退有 guard 测试；完成状态仍需 M4 独立验证证据才能实现。API、并发幂等和注入 Intent 失败后的整体回滚已在真实 PG 通过，完整 crash recovery 尚未验收。
