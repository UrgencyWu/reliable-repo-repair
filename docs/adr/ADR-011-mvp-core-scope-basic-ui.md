# ADR-011: Freeze MVP core scope with a basic React UI

Upstream baseline: `langchain-ai/open-swe@ad545353e2cdb4c7ae1c419f966c82436b63e799`。 日期：2026-09-28。

## Status

Accepted by user; implementation not started。本版范围固定为 [MVP-001 v1.0](../MVP_DEVELOPMENT_PLAN.md)。

## Context

用户同意非核心功能全部延后，同时要求保留基本前端展示，并确认八类核心功能计划。早期文档把 UI 放 Phase 5、SSE/完整故障矩阵/监控平台列入长线目标，容易与本版范围混淆。

## Decision

本版必做 Task/Run、可靠 DispatchIntent、真实 Open SWE Adapter、clean Independent Validator、最小 Recovery、Artifact/Query/结构化日志、两个 React 页面、必要测试/可重复本地部署。UI 提前纳入 MVP，用 REST 轮询，Patch/Validation 在详情页，不增加第三页。

只实现与可信 repository fixture 主链相关的最小幂等/lease/有限 safe retry/unknown result reconciliation/验证恢复。CI 自动触发、SSE、监控平台、跨 Provider 恢复、复杂调度与公共 cancel/manual retry 接口等明确不进入本版。Task 的总预算/执行超时、权限、独立验证和恢复证据仍为必需，不用延后功能替代。

## Consequences

当前以 MVP-001 的 F01–F08 和 M0–M7 作为范围/验收权威。ARCHITECTURE 和执行契约的长期设计继续保留，但延后部分不自动授权实现。原 upstream 功能不删除；日志/events 可为未来 SSE/metrics 留数据，无需先建设服务。

## Validation

文档范围、文件计划、ROADMAP 一致；真实端到端验收必须包括前端创建和结果查看、原 graph 工具操作、PG 持久化与独立 clean validation。文档 checks 不能代替功能/集成 tests。

相关：[Phase 1 文件计划](../architecture/PHASE_1_PLAN.md)、[ROADMAP](../ROADMAP.md)。

## M6 implementation increment — 2026-09-28

两页在原 `ui/src/features/repair` 与 `/repair` 文件路由增量实现，复用 session/RequireLogin/AgentsShell、TanStack Query、Button/Input/Textarea。原 sidebar 增一个入口，routeTree 用原 TanStack 工具生成。列表创建请求保留 payload 对应幂等键，失败重试同 payload 复用 key；表单只接受 fixture identity/完整 SHA/固定失败命令/约束。详情仅渲染已存 timeline、Run/validation 摘要，patch/log 点击后读取，候选 hash 不变时不重复下载；终态停止状态 polling。`VITE_REPAIR_POLL_MS` 默认 4000ms，后台 tab 不轮询。使用只读 unified diff，不引入编辑器/第三页。

Repair endpoints 是 `/api/repair-tasks`，原 Vite/Nitro 同源代理增该前缀，复用 cookie 转发；原 dashboard API path 不改。4 个新组件测试通过（含 terminal polling stop），生产 build 已通过。最初完整 UI typecheck 发现 8 个 fetch/preconnect 和 ghostty test platform 兼容错误；固定 upstream 原 UI 的独立快照实际复现同样问题。

随后小范围修正原 fetch wrappers：保留 runtime fetch 的 enumerable helpers，使用 callable 签名接收 SDK wrapper；原测试保留相同 mocked 行为，platform fixture 使用真实 navigator 字面量。新增测试验证 helper/响应 body/timing 行为，不扩大 Repair 功能。完整 typecheck 已通过，相关 5 files/24 tests 和生产 build 通过。

真实 Chrome 验证页面创建→原 graph 工具修改→独立验证 PASS→COMPLETED→patch bytes/hash→原 thread 单 Run→返回列表终态。发现原 QueryClient 的 30s staleTime 可让返回列表暂时显示旧状态，Repair list 显式 staleTime=0，并通过真实浏览器复验。只读 diff、checks 和列表截图已检查。M6 DONE；Compose/新环境属于 M7，仍未验收，MVP 未完成。

## 2026-09-29 终态查询修复

TIMEOUT 不代表 Runtime 停止意图已完成。详情 polling 仅在 task 终态且所有 Run 的 runtime_stop_pending 均为 false 时停止；pending→confirmed 和 pending→unconfirmed/error 均继续读取最终结果。保持原 REST polling，不增加 SSE。两种新回归及既有四项组件测试通过；pending=false 且 error 非空仍明确表示停止未确认。详见 [修复结果](../reviews/FIX_RESULTS.md)。
