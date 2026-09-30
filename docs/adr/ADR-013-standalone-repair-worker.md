# ADR-013: 独立 Repair Worker 服务

日期：2026-09-28。状态：ACCEPTED，已完成可信本地运行验收。

Upstream baseline: `langchain-ai/open-swe@ad545353e2cdb4c7ae1c419f966c82436b63e799`。

## 背景

MVP-001 v1.0 已完成可信本地验收，Repair Dispatcher 当时由 FastAPI lifespan 启动。用户授权收尾增量：拆分独立 Worker，再在模型配置和预算明确后开展小规模真实模型验收；webhook 保持可选延期。

## 决策

FastAPI 不再启动 Repair Dispatcher。`python -m agent.repair.worker` 是独立进程，负责派发、执行观察、候选收集、独立验证与恢复。保留原 LangGraph Runtime 在 backend，Worker 通过 Runtime API 调用原 Agent。PostgreSQL 保留 transactional Dispatch Intent、SKIP LOCKED、lease/token fencing 与 metadata reconciliation，不新增 MQ。

Compose 四服务：postgres、backend、repair-worker、dashboard。backend 和 Worker 使用同一应用镜像、相同 UID 与 /data 工作卷路径；Local Provider 通过路径关联 Agent 与候选导出。只有 backend 使用 Runtime 状态卷。Worker 不 bootstrap 用户/fixture、不执行数据库 migration；backend 完成原启动/bootstrap 后，Worker 才启动并检查配置及数据库表。

Worker SIGTERM/SIGINT 取消自身调度任务并释放数据库资源；这不等于停止远端 Agent。重启后由原租约/观察/对账机制处理，不重新生成。SIGKILL 仍可能留下验证目录或子进程，维持 MVP 的本地可信边界。

## 验收

必须实际证明 API 在 Worker 停止时接受/查询 QUEUED 任务；独立 Worker 启动后完成同一任务；多 Worker 竞争不产生重复 Run；真实 crash 三窗口仍通过；浏览器经过四服务得到独立 PASS 与 patch。不得用 Compose 可解析替代运行证据。

## 范围

原 MVP 验收保持历史事实；新增结果独立记录。真实模型验收不属于 deterministic CI suite，需要可用凭据及明确费用预算，不能把当前 scripted model 的 PASS 当真实模型能力。没有引入 webhook、Redis、RabbitMQ、Kubernetes 或生产部署。

## 实际结果

四服务真实 build/up：三个有 healthcheck 的服务 healthy，repair-worker 独立进程 running（没有将进程存活宣称为业务 healthcheck）。默认 Chromium 两项通过（14.8s）：停 Worker 后 API 202/查询 QUEUED，启动两个 Worker 后 COMPLETED，单 Runtime Run/单候选；随后浏览器全链 patch/PASS 验收。相关 Adapter/Dispatch/三类真实 SIGKILL 测试12 passed（89.19s），无 skip；后者仍是隔离 schema 的真实 Worker 子进程，不宣称容器级三窗口 SIGKILL 已测试。日志实际包含 service/trace/task/run/thread/runtime_run/validation IDs。
