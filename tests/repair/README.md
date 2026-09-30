# Repair 开发与当前验证

Baseline: `ad545353e2cdb4c7ae1c419f966c82436b63e799`。当前 M0–M7 已完成可信本地验收，见 [验收对照](../../docs/architecture/MVP_ACCEPTANCE.md)。下面是宿主机开发方式；四服务独立 Worker 启动与测试见 [部署说明](../../deploy/repair/README.md)。不是生产部署/真实模型效果或云恢复结论。

## 环境

从仓库根目录执行；需要支持正式 Python 3.14 的 uv 和可工作的 Docker。实际验证使用 uv 0.12.19、Python 3.14.7、固定 `uv.lock`、PostgreSQL 16.15、LangGraph API 0.15.0rc5/SDK 0.4.5。没有修改原 Python 版本要求或 lock。

```bash
uv python install 3.14.7
uv sync --locked --extra dev --python 3.14.7
docker compose up -d --wait postgres
```

原 Compose 将 PostgreSQL 暴露在 loopback 5433。其默认用户名/密码仅用于本地开发，不复制到生产配置。

## 单元与真实 PG 测试

```bash
.venv/bin/pytest tests/repair/test_candidate_patch.py tests/repair/test_state.py -q
TEST_ANALYTICS_POSTGRES_URI=postgresql://postgres:postgres@127.0.0.1:5433/postgres \
  .venv/bin/pytest tests/repair/test_api.py tests/repair/test_dispatch.py -q
.venv/bin/ruff check agent/repair tests/repair
.venv/bin/ty check agent/repair tests/repair
```

PG 测试复用 upstream 的隔离 schema/migration fixture，测试结束删除其自己的 schema。没有上述 PG 配置时 upstream fixture 会 skip，不能视作数据库验收通过。

## 原 Agent 的实际执行测试

终端一，从根目录启动原 LangGraph Server 和 FastAPI app：

```bash
mkdir -p .tools/repair-runtime
E2E_TMP="$PWD/.tools/repair-runtime" \
POSTGRES_URI=postgresql://postgres:postgres@127.0.0.1:5433/postgres \
LANGGRAPH_URL=http://127.0.0.1:2030 E2E_BASE=http://127.0.0.1:2030 E2E_PORT=2030 \
OPEN_SWE_LOCAL_WORKTREES_DIR="$PWD/.tools/repair-runtime/worktrees" \
OPEN_SWE_LOCAL_ARTIFACTS_DIR="$PWD/.tools/repair-runtime/artifacts" \
  .venv/bin/langgraph dev --config tests/repair/langgraph.json \
  --port 2030 --no-browser --no-reload
```

终端二，同样从根目录执行：

```bash
REPAIR_TEST_RUNTIME_URL=http://127.0.0.1:2030 \
OPEN_SWE_LOCAL_WORKTREES_DIR="$PWD/.tools/repair-runtime/worktrees" \
  .venv/bin/pytest tests/repair/test_runtime_integration.py -q
```

测试入口复用 `tests/e2e/fake_llm.py` 的脚本化模型，仅替换 `make_model` 边界。原 `traced_agent`、Deep Agents loop、LangGraph run、middleware 与 shell tool 全部实际执行；没有模型费用，也没有 GitHub/Slack 发送动作。

测试在允许的临时目录创建 broken repository，Agent 实际调用三次 shell tool：失败复现、修改、验证。随后用原 exporter 的 exact-base 模式导出 patch，在另一个干净 checkout 证明 base 失败、patch hash/base 正确、apply 后测试成功。测试清理自己创建的 thread、patch 和工作区。

这是可信本地 shell 执行，**不是强安全云沙箱**。这个单项 smoke 不经过 Repair API/dispatcher；另一个 adapter integration 已通过实际 API/dispatcher→原 graph→PG candidate。正式 Validator 业务结果由 adapter integration 验证并入库。不要使用该测试入口运行不可信外部仓库。

## M1 API 的当前边界

`agent/api/app.py` 已挂载 POST/list/detail。POST 需要 upstream session cookie 和 `Idempotency-Key`；还需配置 `REPAIR_FIXTURES_FILE` 指向 JSON 数组。每个 fixture 保存 `id/source_path/failing_command/target_argv/regression_argv/allowed_patch_paths/shared/allowed_users`，路径由服务配置提供，公共请求不能透传本地路径或任意命令。`shared` 默认 false；仅显式共享或列出的用户可使用。

成功创建会事务保存 Task、首个 Run、Intent、初始 timeline，并返回 202/Location。API 不启动 Repair dispatcher；另一个进程设置 `REPAIR_ENABLED=true` 后执行 `python -m agent.repair.worker`，经 Runtime API 调用原 LangGraph Server，共享同一个 PG 与本地工作卷路径。还需原 `OPEN_SWE_LOCAL_WORKTREES_DIR` 以及 `LANGGRAPH_URL`。原 graph 完成后，候选 hash/base/patch 在 PG 持久化，任务进入 VALIDATING。随后独立 clean checkout 执行原始失败复现、补丁应用与固定 target/regression，保存完整证据；PASS 转 COMPLETED，FAIL/ERROR 转 FAILED。单命令 timeout 可由 `REPAIR_VALIDATION_TIMEOUT_SECONDS` 配置，默认 20 秒。独立 Worker 未启动时，任务保留 QUEUED；`REPAIR_ENABLED` 默认 false，Worker 必须显式开启。五个 API 和两页 UI 均已实现，浏览器使用当前源码的 test-only Server 验证通过。

## API/常驻派发与 Adapter integration

在上述 test-only Server 运行时，从仓库根目录执行：

```bash
TEST_ANALYTICS_POSTGRES_URI=postgresql://postgres:postgres@127.0.0.1:5433/postgres \
REPAIR_TEST_RUNTIME_URL=http://127.0.0.1:2030 \
OPEN_SWE_LOCAL_WORKTREES_DIR="$PWD/.tools/repair-runtime/worktrees" \
  .venv/bin/pytest tests/repair/test_adapter_integration.py tests/repair/test_process.py \
    tests/repair/test_validation.py tests/repair/test_validation_store.py -q
```

测试覆盖两个真实 dispatcher 并发只产生一个 Runtime Run/候选、原 graph + exact-base/hash + clean replay、已创建 Run 的响应丢失后替换 worker 对账、工作区重接保留修改、迟到 execution token 被拒绝、实际 API 接受后再启动独立 Worker 的调度循环。PG trigger 拒绝候选 UPDATE/DELETE；patch 有 5 MiB 上限，MVP 明确拒绝 symlink/submodule patch。命令输出保留最多 1 MiB，超时清理进程组，独立执行不继承主进程凭证环境。正式 Validator、最小 crash/deadline recovery、基本 UI 与 Compose 新环境均已验收。

独立验证测试保存 PASS/FAIL/ERROR 和 baseline/apply/target/regression 的日志及环境摘要。事务测试拒绝缺少回归、替换命令、错误 base/hash 的 PASS；模拟租约中断后接管仍使用同一 candidate，并拒绝旧 token，连续丢失 owner 三次后有界失败。这些测试不调用真实付费模型；实际原 graph integration 使用固定脚本模型。

## M5 结果查询

五个 Repair API 已实现：POST、list、detail、patch、artifacts。所有读取复用 session/用户归属，不存在或其他用户任务均 404。patch 尚未保存时 409 `patch_not_ready`；已有 patch 以原始字节返回，ETag 为保存的 SHA256，`X-Base-Commit` 为完整基准 SHA。

详情只返回 candidate metadata 和 validation summary，轮询不会下载完整 patch 或 validation logs。artifacts 按需读取验证 checks/manifest，全部日志输出总上限 64 KiB，包含 `truncated` 与 `stored_output_bytes`；不返回内部 Agent/Validator filesystem path。每个 fixture 最多 10 条固定 regression commands。新的 Artifact 测试与真实 API/worker integration 验证完整 PASS 的证据和原始 patch hash。本版最小 deadline/restart recovery 已通过真实测试，云/完整 checkpoint 恢复仍延期。

## Deadline / Runtime stop

Dispatcher 每次 tick 使用 DB-time 扫描整个 task deadline（默认 `REPAIR_TASK_TIMEOUT_SECONDS=300`），覆盖 QUEUED/PROVISIONING/VALIDATING/未知创建。活跃本地派发与验证受剩余总预算约束，单验证命令仍有独立上限。TIMEOUT 清除旧 owner token，保留候选和已保存 checks；没有“验证后来通过就改回成功”的路径。

Runtime stop 是持久意图，重启后继续请求 SDK interrupt 并查 terminal；详情 Run 显示 `runtime_stop_pending/runtime_stop_error`。deadline 后 60 秒仍不能确认则停止自动尝试，保留明确 unresolved/unconfirmed 原因，需要检查原 Runtime。pending=false 且 error 非空不代表远程停止；任何 cancel receipt 都不当作进程清理证明。

在上述 PG/Server 环境执行 `tests/repair/test_recovery.py`：验证旧 token/deadline、真实 active Run 被 interrupt 且只一个 Run、未知创建超时不重复派发。OS worker SIGKILL/restart 由下面的独立进程测试提供证据。

## 真实 worker crash/restart

使用相同 PG/Runtime/worktree 环境执行 `tests/repair/test_worker_crash.py`。测试实际启动两个 Python worker 进程，SIGKILL 旧进程，并等待真正的 30 秒 DB lease expiry；不是修改 DB timestamp 或模拟进程异常。三个窗口分别是已有 active Run、Validator 执行中、远程 create 成功但 Runtime ID 未存；均复用原 Run/candidate，最后独立 PASS/COMPLETED，Runtime history 仅一条。测试时长约一分钟量级是等租约的成本，不作为性能 benchmark。

`test_recovery.py` 另验证 Runtime missing、Agent workspace 丢失：已有候选可继续验证，没有候选明确失败。Run 查询含 dispatch_attempts/status、stop_pending/error；timeline 含实际 WORKSPACE_READY、RUNTIME_STARTED/RECONCILED、queue wait/dispatch/reconciliation duration。

SIGKILL 不会执行 worker finally，可信本地模式可能遗留验证目录或在途子进程；测试清理自己的遗留目录，固定短时命令自行结束。不能把这些进程测试描述成强安全 Sandbox 或通用后台进程清理保证。
