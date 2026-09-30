# Roadmap — MVP-001 v1.0

Upstream baseline: `langchain-ai/open-swe@ad545353e2cdb4c7ae1c419f966c82436b63e799`。更新日期：2026-09-30。

当前范围已由用户确认：[核心后端 + 基本前端 MVP 开发计划](MVP_DEVELOPMENT_PLAN.md)。范围固定不等于代码完成；每项 DONE 必须有实际证据，不能用跳过的测试、纸面设计或 mock 页面验收。

## 当前交付状态

当前工程以本仓库为准，保留 Open SWE 上游历史及 Repo Repair 的实现、测试和部署配置。

Redis Streams 增量已完成：PostgreSQL 保存任务与派发意图，Redis Stream 投递 Intent ID，独立 Worker 回数据库领取租约。真实 PostgreSQL/Redis 相关测试 19 项通过，隔离五服务 Chromium 全链测试 1 项通过；见 [验收记录](architecture/MVP_ACCEPTANCE.md)。

增量审查修复（与下文收尾增量编号区分）：审查 R1/R2/R3 已实施锁后有效性校验、对账冲突隔离/退避及 Runtime 停止结果轮询。验证结果见 [修复计划](reviews/FIX_PLAN.md) / [修复记录](reviews/FIX_RESULTS.md)，不扩大 MVP 范围。修复后 Compose 已重建，2 项 Chromium 部署验收通过，原 6 个任务保留，见 [部署验收](reviews/DEPLOYMENT_ACCEPTANCE.md)。

收尾增量 R1：独立 Repair Worker 服务已完成，见 [ADR-013](adr/ADR-013-standalone-repair-worker.md)。R2：小规模本地真实模型实验使用 8100 服务 `qwen3.8-27b`，13 个合成任务固定验证通过、事后补充契约检查 11 个通过/2 个失败，见 [实测报告](architecture/REAL_MODEL_ACCEPTANCE_RESULTS.md)。R3：Redis Streams 投递与五服务运行已完成。CI webhook 仍列在后续范围。

R2 后续独立实验：补强两个已暴露的契约缺口，2 个新任务固定验证通过；再从 Requests 官方 tag 提取包源码，验证两件可复现历史 issue 的候选，2 个固定验证与事后额外检查通过。两组均有独立 manifest，不回写首轮分母；源码提取不等于完整上游仓库或盲测。详见 [复测报告](architecture/REAL_MODEL_FOLLOWUP_RESULTS.md)。

R2准备阶段仅验证合成样本有效性；本次正式实验另建四服务/独立数据卷与 session，先冻结 10 个单文件任务，再冻结 3 个多文件任务，并保存所有真实 RepairTask、候选、独立日志及主 Agent 回执。中位业务耗时 23.202 秒，累计主 Agent Token 1,110,734，费用 UNKNOWN。两个补充失败说明需求与固定测试仍需完善，原记录保留，不将 13/13 固定 PASS 说成语义正确率；详见 [验收边界](architecture/REAL_MODEL_ACCEPTANCE.md)。

| 工作 | 状态 | 证据与边界 |
|---|---|---|
| Phase 0: Upstream Audit | DONE：静态源码审查 | 官方 remote/SHA/tag/branch、source/module/provider/state/UI/CI、风险与文件计划；不含 Runtime pass |
| Python 复用与执行契约 | DONE：设计与核心本地验收 | ADR-007/008/009/010、Task/Run/Intent、clean Validator/recovery 对应 M0–M5 证据 |
| MVP 范围固定 | DONE：用户确认与文档 | MVP-001 v1.0、ADR-011；F01–F08 必做、两个 UI 页面与 polling、明确延后功能 |
| MVP 实施与运行验收 | DONE：MVP-001 v1.0 可信本地范围 | M0–M7 实际证据；新独立 volumes/三容器 healthy；真实浏览器→原 Agent→独立验证→patch/列表；相关集成/故障 checks 通过；不是生产或真实模型效果验收 |

## 本版里程碑

相关 tests 随每个模块同步开发；不是最后统一补测试。

| 里程碑 | 实施范围 | 当前状态 |
|---|---|---|
| M0 | Python/locked install、原 Server/PG、真实 graph + deterministic model、SDK identity/query 与 patch replay | DONE：Python 3.14.7、API 0.15.0rc5/PG16、真实 graph 工具与 clean replay 通过；不代表 crash recovery |
| M1 | Task/Run schema、migration、state、auth/ownership、POST/list/detail | DONE：真实 PG migration/API/并发幂等/事务回滚与状态 guard 测试通过 |
| M2 | dispatch intent/幂等/claim/lease/token/有限 safe retry/RECONCILING | DONE：常驻 dispatcher/双实例并发、接受后再启动 worker、真实 Run 响应丢失后的对账通过；全程 crash/deadline 分类由 M5 验收 |
| M3 | Open SWE Adapter、thread/runtime run/sandbox 关联、不可变 candidate | DONE：真实原 graph、独立 local checkout、hash/base/文件策略、PG immutable candidate 与执行租约已验证 |
| M4 | clean Validator、base failure/apply/固定 tests/regression、PASS/FAIL/ERROR | DONE：独立 clean base failure/apply/固定 target+regression、PASS/FAIL/ERROR 持久化与接管租约测试通过 |
| M5 | 最小 restart recovery、artifact/query、事件/关联日志/耗时 | DONE：结果查询/有界日志、deadline/Runtime interrupt、三个真实 SIGKILL 窗口与 workspace/runtime loss 分支通过 |
| M6 | React 列表含创建表单、详情含 diff/validation/log、REST 轮询 | DONE：24 项相关 UI tests、完整 typecheck、生产 build、真实 Chrome 创建/独立 PASS/patch hash/单 Runtime Run/列表终态与截图检查通过 |
| M7 | Compose、真实 integration/browser smoke、README 新环境复跑、阶段证据 | DONE：真实镜像 build/新 volumes 初始化/三 healthy；Linux Repair58 tests+4subtests 无 skip；补充分页1与最终PATH相关21通过；容器浏览器最后1 passed；普通重启保留已有完成结果；远程 CI 未运行 |

基本前端不是 Phase 5 才做的可选项。后端 API 完成但缺 UI、mock adapter 代替真实 graph、容器未启动或 integration skip 均不能标 MVP DONE。当前文件级工作见 [PHASE_1_PLAN](architecture/PHASE_1_PLAN.md)。

## 本版实际修改与前置未知

保留原仓库/历史/LICENSE 与 Python/JS lock。已新增 `agent/repair/`、migration 0042–0045、Repair router/lifespan/dispatcher/adapter/独立 Validator、真实 graph 测试入口及相关测试；对原 patch exporter 增加 optional exact-base/path 模式，原默认导出测试仍通过。两页 UI、部署与新环境已验收，原 fetch wrapper/测试类型小范围修正，Git 机器输出与 stderr 分离。证据见 [验收对照](architecture/MVP_ACCEPTANCE.md)、[VALIDATION](upstream-analysis/VALIDATION.md)、[开发说明](../tests/repair/README.md) 和 [本地部署](../deploy/repair/README.md)。

已确认 SDK 0.4.5 的 `runs.create` 不支持 caller-specified run id；预创建 thread 并通过 `runs.list` 的业务 metadata 找到原 run。一次空查询不能排除在途创建。常驻派发、双 dispatcher、响应丢失、三个真实 worker SIGKILL 窗口、deadline、不可恢复分类、基本前端与 Compose新环境已通过。完整 Runtime crash、云 Sandbox 恢复/生产部署不在本版。Java 不再是前置条件，明确延期项未新增实现。

原 30–50 人日估计覆盖更大的多阶段目标，不作为本次缩减后 MVP 的工期承诺。先用 M0/M1 实际结果校准剩余工作，不以未验证 Runtime 假定排出精确日期。

## 当前不开发的后续阶段

以下均为 **DEFERRED：本版不实施**，重新纳入时更新计划版本与 ADR。

| 原阶段/类别 | 延后范围 |
|---|---|
| Phase 2: Reliability expansion | 公共 cancel/manual retry、完整恢复/Provider 矩阵、通用 snapshot/跨云容灾、动态调度；本版最小可靠性仍必做 |
| Phase 3: CI Repair | webhook 自动触发、GitHub App 完整授权、CI job/log ingestion、Backend 自动多轮修复、自动 Draft PR |
| Phase 4: Observability/analysis | Prometheus/Grafana/集中日志/完整 tracing、性能 benchmark、EXPLAIN 优化前后实验；本版日志/耗时/必要索引与 tests 必做 |
| Phase 5: Frontend expansion | SSE、第三个 Patch 页、交互编辑器、图表/高级搜索；本版两个基本页面必做 |
| Phase 6: Production deployment | 生产部署专项、Kubernetes、多租户/复杂 RBAC；本版可重复本地 Compose 必做 |
| 可选栈/泛化 | 新 Java/Go 服务、RabbitMQ/Redis/MySQL、多 Agent/动态模型/插件、多平台/并行验证、完整 ToolCall 镜像 |

不删除 upstream 的已有功能，不将已有产品能力当作 Repair 场景已验收。具体延后清单以 MVP-001 第 6 节为准。

## 阶段更新规则

每个里程碑：运行相关 unit/integration/fault/frontend checks，记录 pass/skip/fail 与限制，检查 git diff，更新实际变更、ADR/ROADMAP。最终需前端→PG→原 Runtime/Agent→clean Validator→结果前端的真实完整链。secret 不进入 Git，不写伪性能/成功率结果。
