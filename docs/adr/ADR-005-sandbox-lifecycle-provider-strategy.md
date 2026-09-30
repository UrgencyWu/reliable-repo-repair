# ADR-005: Sandbox lifecycle and provider strategy

Upstream baseline: `langchain-ai/open-swe@ad545353e2cdb4c7ae1c419f966c82436b63e799`。日期：2026-09-28。

## Status

Accepted reuse strategy; enforcement experiments pending。该状态是架构决策状态，不是功能已实现。

## Context

upstream支持LangSmith/E2B/Daytona/Modal/Runloop/local，各资源/TTL能力不同。local忽略id且在host执行。lifecycle区分unreachable与gone，gone可重建但无法还原未提交工作。

## Decision

2026-09-28 revision：按 ADR-007/008 改用原 PostgreSQL，业务/Agent/Sandbox 权威边界保留。

复用SandboxBackendProtocol/registry/lifecycle；以threadmetadata绑定为云provider依据、PostgreSQL存projection/policy/retention。Phase1仅可信fixture本地执行，Agent 与 Validator 使用独立 checkout；Generation/Verification 边界由 ADR-009 细化；云provider策略逐项验证，不能从policy字段存在推断enforcement。

## Consequences

保留unreachable原id；deleted标记workspace loss并用artifact/snapshot恢复或新attempt，禁止静默重建后继续旧checkpoint。不forcecheckout已有workspace。保留恢复窗口，不task完成即盲删；orphan/cleanup机制需provider证据。Docker不是强安全Sandbox。

## Validation

Phase1fixture工具测试；Phase2workercrash+保留patch恢复、unreachable/deleted分支；云TTL/CPU/内存/网络/secret/process cleanup实验现在UNKNOWN。

M3 实施证据：可信本地路径采用 upstream desktop 的 allowlisted LocalShellBackend，原 graph/tool 实际执行。每个 RepairRun 在配置 worktree root 下有自己的 clone 与 base manifest；重接读取已有 workspace，不强制 checkout，测试证明修改保留。不宣称这条本地路径是强安全 Sandbox，也不创建虚构的云 sandbox id。准备/验证命令的受限子进程环境、1 MiB 输出上限和超时进程组清理由测试验证；这不代表已验证原 Agent 的所有后台子进程/云资源清理。

相关：[Upstream审查](../upstream-analysis/OPEN_SWE_ARCHITECTURE.md)、[目标架构](../ARCHITECTURE.md)、[Phase1计划](../architecture/PHASE_1_PLAN.md)。
