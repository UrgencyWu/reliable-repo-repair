# MVP-001 v1.0 验收对照

Upstream baseline: `langchain-ai/open-swe@ad545353e2cdb4c7ae1c419f966c82436b63e799`。日期：2026-09-28。范围依据 [固定计划](../MVP_DEVELOPMENT_PLAN.md)，详细执行记录见 [VALIDATION](../upstream-analysis/VALIDATION.md)。

下表来自实际源码、数据库、测试报告与浏览器，不把设计文档当运行证据。**F01–F08/M0–M7 在固定 MVP 的可信本地范围完成**。全量原项目测试/生产部署/延期功能不在本次结论中。

## 功能对照

| 功能 | 实现与约束 | 实际证据 |
|---|---|---|
| F01 Task/Run | `agent/repair/{models,api_models,state,service,store,routes}.py`；原 session/owner/受授权 fixture；严格转移、终态、bounded list/detail | `test_api.py` POST202/持久化、8 个并发重复/异 payload409、事务回滚、匿名/越权与 DTO；`test_state.py` 终态/非法转移；实际跨页/tie/owner 测试宿主机和 Linux PG 均通过 |
| F02 派发 | 同 TX Task/Run/Intent/events；PG unique/SKIP LOCKED/DB-time lease/token；bounded safe retry/backoff；未知创建 RECONCILING | `test_dispatch.py` 双 claim、expiry、unknown creation/backoff/exhausted/deadline；真实 API worker 后启动与双 dispatcher；真实远程 create 成功但 reference 未落库 SIGKILL 窗口 |
| F03 原 Agent Adapter | `adapter.py` 调用 SDK/original graph；预建 thread、metadata find、workspace/run 关联；exact SHA/typed input；原 exporter 严格模式 | `test_runtime_integration.py` 与 `test_adapter_integration.py` 实际 shell fail/edit/pass；`test_candidate_patch.py` committed/staged/untracked/binary 重放、symlink/submodule拒绝、默认兼容；PG trigger 实际拒绝 candidate UPDATE/DELETE |
| F04 独立 Validator | 全新 checkout、不可变 base/hash/file policy、base fail/apply/固定 target+regression、证据事务；PASS 才完成 | `test_validation.py` 13 项正/负例与环境污染；`test_validation_store.py` 完整证据/错误命令/旧 owner/预算；真实容器浏览器 `[1,0,0,0,0]` PASS；stdlib fixture 基础 Python/-S 不加载 Agent 可变 packages |
| F05 最小 Recovery | durable claims/observer/候选与验证接管；旧 token/deadline 拒绝；Runtime/workspace missing 明确失败；stop receipt 不当清理证明 | `test_recovery.py` 六类分支；`test_worker_crash.py` 三个真实 Python SIGKILL/实际30s lease等待、同 Run/candidate/单 Runtime history、最后独立 PASS |
| F06 结果/events/log | patch 原始字节/hash/base；summary 轮询不载大内容；按需 artifacts 输出64KiB cap；阶段/IDs/耗时/attempt/failure | Artifact/API tests 对其他 owner404、匿名401、未就绪409、UTF8截断与内部路径不泄露；浏览器 patch SHA与持久 candidate一致；PG主环境 task/run/intent/candidate/PASS各一条 |
| F07 两页 UI | 原导航/session/shell/components；列表含创建/分页；详情 timeline/readonly diff/checks/logs；活动轮询、终态停止/隐藏不轮询 | `RepairTasks.test.tsx` 4项、appLocation相关测试；固定 Node/pnpm 38项相关 UI测试、typecheck/build；容器 UI→原 Agent→独立验证→patch→列表 COMPLETED 真实 Chrome 单项通过，截图实际检查 |
| F08 工程 | migration0042–45、索引/事务、外置私有config、固定锁文件、三容器、本地 fixture/session、增量 CI、从零说明 | 全新 PG16.15 initial repair_task count0/migration head14940cd67eb6；两个真实镜像 build；三个 healthy；Linux相关 Repair58 tests+4subtests，JUnit62/0failure/0error/0skip；浏览器真实通过；相关 lint/types/format；原 remote/SHA/LICENSE/locks保留 |

## 最终链路与数据

实际新 volumes 的 Compose：`postgres`、`backend`、`dashboard` healthy。backend 原 LangGraph API0.15.0rc5/runtime-inmem0.35.0rc5/DeepAgents0.7.17，Python3.14.7/uv0.12.19；UI Node24.13.1/pnpm11.22.0/原 JS lock；PG16.15 Linux arm64。

真实 Chrome 在3012创建，2032原 Runtime执行，独立 fresh checkout验证，回写PG后读取原始patch。主业务数据库核对：Task1、COMPLETED1、Run1、DISPATCHED Intent1、Candidate1、PASS Validation1。patch SHA256 `5b866a798161e0e41223ff27213b59acc3c500a38a534990126aa1508b1f1f24`；这是一份 fixture 结果，不是模型成功率或性能指标。

报告位于 ignored `.tools/repair-compose-test-results.xml`、`repair-compose-tests.log`、`repair-compose-final-browser.log`、`repair-compose-business-evidence.json` 与截图目录。最后 backend source重建后 Linux 分页1 passed；验证 PATH 排除 Agent virtualenv 后相关21 passed，最终浏览器1 passed（8.1s）；普通 backend重启保留原 COMPLETED任务，随后新任务仍各一个 Runtime Run。文档保留命令/版本/真实结果以便重跑，不依赖分享本机缓存或私有会话。

补充最终复验使用 Playwright 默认 Chromium，约束留空、请求不携带专用测试 marker：容器全链路1 passed（6.0s），记录 `.tools/repair-compose-no-marker-browser.log`。上述数据库各1条是首次链路核对时的记录；后续复验正常创建新任务，每个任务仍核对单个 Runtime Run，不声称当前全库只有1条任务。

## 边界

MVP 是可信 stdlib fixture 的本地 Repo Repair，不是自动 CI ingestion 或生产部署。模型 seam 是 deterministic model，Agent/Runtime/tools/PG/Validator真实；不宣称 paid model 智能修复效果。

Local Provider/普通容器不是强安全 Sandbox。共享基础不可变工具不代表云网络/资源策略已实现；其他 fixture 必须配置独立受控依赖，复杂矩阵延期。SIGKILL 可遗留目录/子进程，测试只清理自己的短时命令/目录。dev Runtime 文件卷不等于 full checkpoint/Runtime crash容灾。SDK不支持 caller RunID，未知创建不盲目重发，不承诺 exactly-once。

GitHub Actions 文件已配置，远程未执行；没有 commit/push/PR/部署发布。CI webhook、GitHub App新产品、自动PR、SSE、公共cancel/retry、metrics平台、Kubernetes等保持 DEFERRED。Redis Streams 增量见文末独立验收记录。

相关：[从零部署](../../deploy/repair/README.md)、[ROADMAP](../ROADMAP.md)、[ADR-012](../adr/ADR-012-reproducible-local-repair-demo.md)。

## R1 收尾增量：独立 Worker

原三服务/MVP测试批次是历史证据。R1 时源码已删除 Repair API lifespan hook，`agent/repair/worker.py` 为独立入口；当时 `compose.repair.yaml` 含 postgres/backend/repair-worker/dashboard 四服务，保留原 Runtime，Worker使用相同应用镜像与 /data 路径，经Runtime API协作。当前配置已增加 Redis 服务。

| 要求 | 当前实际证据 |
|---|---|
| API与Worker独立生命周期 | Chromium停止Worker后API仍202/查询QUEUED，启动Worker后同任务COMPLETED |
| 多Worker竞争 | 同一浏览器测试启动两个实际Worker容器，检查单Repair Run/单Candidate/单Runtime history；finally恢复一个Worker |
| crash/reconciliation/fencing保持 | 当前Linux Adapter/Dispatch/三个真实SIGKILL子进程窗口12 passed（89.19s），JUnit零failure/error/skip；不将子进程证据说成容器三窗口注入 |
| 四服务结果展示 | 默认Chromium完整patch/独立PASS/UI验收，两项合计14.8s；三个有healthcheck服务healthy，Worker running且真实处理任务 |
| 配置与记录 | README/ROADMAP/部署说明/[ADR-013](../adr/ADR-013-standalone-repair-worker.md)/VALIDATION更新；Worker JSON日志包含关联IDs |

R1 DONE；R2真实模型验收尚无模型调用、成功率或费用记录，见 [真实模型验收边界](REAL_MODEL_ACCEPTANCE.md)。

## Redis Streams 增量验收（2026-09-30）

当前 Compose 增加 Redis 7 服务及 AOF volume。API 在 PostgreSQL 同事务写 Task、Run、Intent 和事件；独立 Worker 发布 Intent ID 到 Stream，消费组通过 PostgreSQL 锁和租约领取任务。`repair_dispatch_intent` 增加 `redis_stream_id`、`redis_published_at`，记录最近一次投递。

使用独立 PostgreSQL 16 和 Redis 7 容器运行 `tests/repair/test_stream.py`、`test_api.py`、`test_dispatch.py`，结果为 19 passed、0 failed、0 skipped。Stream 测试逐项注入并核对数据库状态：提交后 `XADD` 失败仍保留待处理 Intent；`XADD` 成功但投递标记未保存会重复发布但仅建立一个派发引用；重复消费只有一个 Worker 获得租约；消息已消费但 Worker 崩溃由 `XAUTOCLAIM` 接管；数据库领取后崩溃转入 `RECONCILING`；删除 Stream 后由待处理 Intent 重建并成功派发。另有并发锁测试确认消费者等待发布器短事务释放 Intent 行锁后立即领取，避免消息滞留 45 秒。

隔离 Compose 项目使用独立端口与 named volumes 启动 postgres、redis、backend、repair-worker、dashboard，五服务均达到健康状态。首次浏览器任务卡在 `QUEUED`，定位为发布标记写入与 `SKIP LOCKED` 领取之间的竞争；修复为按 Intent ID 等待行锁后，重建 Worker 镜像并复跑同一 Chromium 测试，1 passed（6.3 秒），页面展示 `COMPLETED`、候选补丁、独立 PASS 和下载哈希一致。此前四服务浏览器与真实模型实验属于接入 Redis 前的历史批次。
