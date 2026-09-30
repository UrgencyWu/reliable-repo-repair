# Phase 1 / MVP-001: Python 与基本前端文件级开发计划

Upstream baseline: `langchain-ai/open-swe@ad545353e2cdb4c7ae1c419f966c82436b63e799`。设计日期：2026-09-28。

范围依据：[MVP-001 v1.0](../MVP_DEVELOPMENT_PLAN.md)，用户已确认。基本前端纳入验收，非核心功能当前不开发。

状态：**固定文件级计划，对应 M0–M7 可信本地验收已完成**。证据见 [ROADMAP](../ROADMAP.md) 与 [验收对照](MVP_ACCEPTANCE.md)。保留 Open SWE 原布局，在 `agent/repair/` 增量开发。主链 POST → PostgreSQL → durable intent → 原 Runtime/Agent → fixture → candidate →clean-base/独立验证 → GET/基本前端。Gate 是工程验证，不是额外审批。

## Gate 1：真实 Agent 与调度契约

1. 建立 Python >=3.14 环境，`uv sync --locked --extra dev`；不降 requires-python 或随意改 lock。
2. 启动固定版本 LangGraph dev Server 与 PG16。根 Dockerfile/API 配置版本漂移必须先确认，不视作可用 production image。
3. 无付费 model/network 凭证环境，探测 `agent` graph 的 thread create/run/tool 路径；如必须注入 fake model，只加 optional typed factory seam，覆盖 main/title/subagent/offload/fallback；保留默认行为。
4. deterministic model 在真实 graph 中调用 file/shell 工具，对已知 fixture 完成 fail → edit → pass；SDK mock 不能替代该测试。
5. 验证 run create/observe、metadata correlation、调用方 run id 支持与冲突语义；创建结果未知时如何查找既有 run，是 dispatch/recovery 设计的前置证据。无法安全查明时不自动重发，记录未决 intent。
6. 验证 trusted local checkout、allowlist、provider 输出契约，禁止强制 checkout 破坏 resume；SDK config 不由用户透传。
7. 验证候选 patch 的 explicit repo/base SHA 导出与 clean-base replay；既有 recovery patch merge-base 不能直接作为 Repair 的 base。

已通过固定 lock Server/PG 启动、test-only fake model 驱动真实 graph、metadata 查询与 exact-base replay。SDK 不支持 caller-specified run id；在途创建和 Backend restart recovery 仍未完整验证。若本 SHA 有具体兼容问题，先最小修复并记录；改历史基线也须新 SHA/ADR/差异审查，不直接跟 main。

核心契约：[Task/Run、Dispatch、Recovery 与独立验证](REPAIR_EXECUTION_CONTRACT.md)。

## 1A. Repair 业务模块

| 拟新增文件 | 职责 |
|---|---|
| `agent/repair/api_models.py` | typed create/query/result DTO、validation、分页、错误 schema |
| `agent/repair/routes.py` | POST202、GET/list；复用 principal/repo scopes 与 task ownership |
| `agent/repair/models.py` | RepairTask/RepairRun/DispatchIntent/Event/Artifact/ValidationResult ORM；引用原 repo/身份 |
| `agent/repair/state.py` | enum、显式合法边、terminal guards；不从 LLM 文字猜状态 |
| `agent/repair/store.py` | async SQL 查询、短事务 SKIP LOCKED claim、lease/token、幂等约束与事务内持久化 |
| `agent/repair/service.py` | create/query/complete 用例；状态与结果/event 同事务 |
| `agent/repair/config.py` | external typed 配置、fixture allowlist、deadline/轮询预算 |
| `agent/repair/lifecycle.py` | app lifespan 启停 dispatcher/observer，关闭任务、单 event loop |
| `agent/database/migrations/versions/<generated>_repair_tasks.py` | 通过原 `make migration` 生成；新表和必要 indexes |

最小修改 `agent/api/app.py` 挂载 feature router/lifecycle；业务逻辑不进入 `agent/dashboard/routes.py` 聚合器。根 `pyproject.toml`/lock 仅在确有新依赖时增量修改，不创建第二套 Python dependency project。

共享 PostgreSQL 不代表任意模块可写 task status；所有业务写入经 service。可信 fixture identity 与 GitHub repo identity 显式区别；生产 repo 复用已有 Repository。

## 1B. Dispatch 与 Agent adapter

| 拟新增文件 | 职责 |
|---|---|
| `agent/repair/dispatch.py` | 从持久化 intent 认领、有限 retry、stale lease/未知创建 reconciliation、创建/关联 run；无模型 reasoning |
| `agent/repair/adapter.py` | typed input/result 与 OpenSweAgentAdapter；依赖注入 SDK client |
| `agent/repair/repository.py` | Agent 初始 checkout/精确 SHA；resume 保留 workspace；创建独立 clean Validator checkout |
| `agent/repair/recovery.py` | 原 run/sandbox/已保存 candidate 分类，重接 observer 或 validator；不盲目重启 generation |
| `agent/repair/validation.py` | 固定计划、clean base failure →apply candidate →target/regression checks；PASS/FAIL/ERROR 和独立 evidence |
| `agent/resources/prompts/repair/task.md.jinja` | CI Repair 指令，使用原 prompt loader |

原 `agent/dispatch.py`/SDK 为接入边界，先排除 Slack/PR 等产品副作用；不复制 `create_deep_agent`。SDK 不明确支持的能力标 UNKNOWN。Phase 1 加最小 lease/token 和 RECONCILING 分支，安全 dispatch failure 才有限 retry；完整 budget/renew/cancel/deadline 故障矩阵在 Phase 2；不是依赖一次性 FastAPI BackgroundTasks 保证任务不丢。

HTTP 提交先事务落 intent；进程重启扫描未决 intent。不能在持有 DB 行锁时等 shell/LLM。generation 结束后先持久化 candidate，再 clean checkout 验证。只有 PASS 和完整证据可 COMPLETED；Phase 1 FAIL/ERROR 写明确 failure reason，后续按 validation 与 repair budget 分别重试。

候选 patch 复用 `agent/resources/recovery_patch.py`/`agent/threads/diffs.py`，仅按需要加 optional explicit base/path seam 或共享 helper；Repair 不使用 merge-base fallback，默认 dashboard 保留。新增 `tests/repair/test_candidate_patch.py` 验证 staged/unstaged/committed/new-file 的 exact-base replay；不支持的类型明确失败。

## 1C. 测试与部署

| 拟新增文件 | 职责 |
|---|---|
| `tests/repair/test_state.py` | 非法边、终态、重复完成、phase 最小链 |
| `tests/repair/test_api.py` | 202/404/validation/有限分页、授权与 ownership |
| `tests/repair/test_dispatch.py` | 重复 intent、并发 claim、lease expiry、旧 token 迟到、create 结果未知 |
| `tests/repair/test_validation.py` | clean workspace、base 未失败、wrong hash/base/apply、FAIL/ERROR/timeout；独立环境/结果 |
| `tests/repair/test_recovery.py` | run active 重接、sandbox gone/unreachable、candidate 后 crash、Validator crash 不重启 Agent |
| `tests/repair/test_open_swe_harness.py` | 原 graph + deterministic model +真实 file/shell fixture |
| `tests/repair/test_vertical_slice.py` | 实际 PG/API/dispatcher/Runtime/graph/candidate/clean Validator/GET 链；无付费模型 |
| `tests/repair/fixtures/broken_repo/` | 小 repository、失败测试与稳定修复，无外部依赖 |
| `deploy/docker/compose.repair.yml` | PG16 与兼容的 Agent Server；必须能访问已构建的基本 UI（可由原 FastAPI 静态挂载）；volumes/healthchecks |
| `deploy/docker/runtime.Dockerfile`、`langgraph.repair.json` | 固定版本的 dev runtime；不宣称 production license 已解决 |
| `deploy/docker/repair.env.example` | 无 secret 配置示例、已知端口 |
| `scripts/repair/create_fixture.py`、`scripts/repair/smoke.py` | 初始化精确 SHA、POST →有 deadline 的 poll →验证结果 |
| `.github/workflows/repair-ci.yml` | focused Python checks 与 integration；保留原 workflows |

复用现有 pytest/async/PG isolated fixture，集成测试可用 Python Testcontainers 启动真实 PG；不使用 SQLite 替代 PG 专用 SQL。fake adapter 只验证业务层，不能当真实 graph 通过证据。容器/依赖缺失须报告未执行，不能 skip 后标完成。

## 1D. 基本前端（纳入本版，两个页面）

沿用现有 `ui/src/routes/` 文件路由和 `ui/src/features/` feature 结构；以下路径为拟新增，不表示文件已存在：

| 文件 | 职责 |
|---|---|
| `ui/src/routes/repair.tsx` | 共用 layout/session/access shell；不是第三个页面 |
| `ui/src/routes/repair/index.tsx` | 任务创建表单、列表、基本分页、进入详情 |
| `ui/src/routes/repair/$taskId.tsx` | 状态/真实阶段记录、Patch/validation/log/failure reason |
| `ui/src/features/repair/api.ts` | typed DTO 与五个 REST API，复用现有请求/session 基础 |
| `ui/src/features/repair/queries.ts` | TanStack Query、活动任务轮询、终态停止、按需 artifact 查询 |
| `ui/src/features/repair/RepairTaskForm.tsx` | repository/commit/command/约束、validation 与错误反馈 |
| `ui/src/features/repair/RepairTaskList.tsx`、`RepairTaskDetail.tsx` | loading/empty/error、基本字段和结果；不扩大 UI scope |
| `ui/src/features/repair/RepairDiff.tsx` | 复用现有 diff 组件或只读 unified diff；不做交互编辑器 |
| `ui/src/features/repair/RepairTasks.test.tsx` | 创建、list/detail、fail/result、轮询终止等可观察行为 |
| `tests/e2e/tests/repair_tasks.spec.ts` | 真实 backend/browser fixture smoke；不替代 Python integration |

`ui/src/routeTree.gen.ts` 按原工具生成；必要时给原导航加一个 Repair 入口，不重做 shell/design system。URL 相对原 UI basepath，启动文档写真实地址。使用 pnpm 和现有 lint/typecheck/test 配置，只跑相关 checks。

M6 实际选择将基本 form/query/只读 diff 分别放在两个 feature components 中，未创建额外 queries/form/diff 文件；保持 typed API 和两页边界，避免无必要拆分。真实浏览器文件为 `tests/e2e/repair-tests/repair.spec.ts`，独立配置 `playwright.repair.config.ts`；现已验收。

不做 SSE、第三个独立 Patch 页、高级筛选、统计/图表、交互编辑器；Patch/Validation 直接放详情。前端必须创建并查看真实修复任务，不接受纯静态 mock 页面作为验收。

## API contract v1

POST 输入：repo identity（Phase 1 配置的 fixture id）、完整 commit SHA、failing_command、constraints；返回 202 + Location + id。任意本地路径不作为公共输入，可信 fixture 命令范围明确。重复 Idempotency-Key 同 payload 返回原任务，不同 payload 返回 409；DB unique 持久兜底。

额外必做 `GET /api/repair-tasks/{id}/patch` 与 `GET /api/repair-tasks/{id}/artifacts`，权限同 task；返回 persisted patch 与有界日志/验证 metadata，未就绪明确表示。GET detail 包含实际阶段 events 摘要供轮询，无独立 SSE events API。

GET：status、attempt、created/updated、输入摘要、thread/run/sandbox references、validation 与 patch metadata；不存在 404。list 用稳定 created/id 排序与 size 上限。复用原 auth primitives，显式检查 owner/repo；不增加 Java callback/shared service token 层。

## Phase 1 验收证据（按 Python 复用方案修订）

| 业务条件 | 必须实际验证 |
|---|---|
| 必要服务可启动 | Compose 真实 healthy/log，非只 config 可解析 |
| 创建/持久化/查询 | POST202、PG 实际记录、GET 正确结果 |
| 长任务异步 | HTTP 不等待 Agent；intent 和 Runtime run 有关联 |
| 实际执行 | 原 Open SWE graph API、真实 tool path、fixture fail/edit →candidate →clean Validator pass |
| 结果可信 | clean-base apply、固定测试与回归、独立 exit/output/environment、patch hash，PG 终态事务 |
| 最小可靠性 | 并发 claim/lease/token；重启发现待派发任务；未知创建结果不盲目重发；candidate/验证重接 |
| 测试 | meaningful unit tests、至少一个完整 integration test 真正 pass |
| 基本前端 | 两页面：浏览器创建/list/detail、Patch/validation/log；轮询与终态停止；真实后端 smoke |
| 可复现 | README 新环境运行步骤、依赖版本、无付费模型 fixture 模式 |

旧 Spring/MySQL/RabbitMQ 条件已不作为此 native slice 的默认组件验收，相关专项实验未完成且不能用 native 结果替代。完整可靠恢复留 Phase 2，Sandbox 云隔离留 provider 实验。

顺序：runtime/harness gate → domain/migration/auth/API → durable intent/adapter → validation/最小 recovery → 两页基本 UI → Compose/integration/browser smoke → README/ROADMAP/ADR。具体 M0–M7 与最终证据以 MVP-001 为准。Phase 1 不做 Go 服务、GitHub App 完整授权、自动 PR、Kubernetes 或 Grafana 大屏。
