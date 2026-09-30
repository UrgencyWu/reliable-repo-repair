# Repair 开发与当前验证

Baseline: `ad545353e2cdb4c7ae1c419f966c82436b63e799`。当前 M0–M3 已验证，M4 独立 Validator 待接入。下面是开发测试方式，**不是完整 MVP 的运行验收**。

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

成功创建会事务保存 Task、首个 Run、Intent、初始 timeline，并返回 202/Location。配置 `REPAIR_ENABLED=true` 时，原 app lifespan 启动常驻 dispatcher；复用同一个 LangGraph Server/PG。还需原 `OPEN_SWE_LOCAL_WORKTREES_DIR` 以及 `LANGGRAPH_URL`。原 graph 完成后，候选 hash/base/patch 在 PG 持久化，任务进入 VALIDATING。随后独立 clean checkout 执行原始失败复现、补丁应用与固定 target/regression，保存完整证据；PASS 转 COMPLETED，FAIL/ERROR 转 FAILED。单命令 timeout 可由 `REPAIR_VALIDATION_TIMEOUT_SECONDS` 配置，默认 20 秒。`REPAIR_ENABLED` 默认 false，此时任务保留 QUEUED 等待后续启动。patch/artifacts API 已实现，UI 在后续里程碑实现。

## API/常驻派发与 Adapter integration

在上述 test-only Server 运行时，从仓库根目录执行：

```bash
TEST_ANALYTICS_POSTGRES_URI=postgresql://postgres:postgres@127.0.0.1:5433/postgres \
REPAIR_TEST_RUNTIME_URL=http://127.0.0.1:2030 \
OPEN_SWE_LOCAL_WORKTREES_DIR="$PWD/.tools/repair-runtime/worktrees" \
  .venv/bin/pytest tests/repair/test_adapter_integration.py tests/repair/test_process.py \
    tests/repair/test_validation.py tests/repair/test_validation_store.py -q
```

测试覆盖两个真实 dispatcher 并发只产生一个 Runtime Run/候选、原 graph + exact-base/hash + clean replay、已创建 Run 的响应丢失后替换 worker 对账、工作区重接保留修改、迟到 execution token 被拒绝、实际 API 接受后再启动 lifespan/background loop。PG trigger 拒绝候选 UPDATE/DELETE；patch 有 5 MiB 上限，MVP 明确拒绝 symlink/submodule patch。命令输出保留最多 1 MiB，超时清理进程组，独立执行不继承主进程凭证环境。正式 Validator 已验收；完整进程 crash/deadline recovery、UI/Compose 验收尚未完成。

独立验证测试保存 PASS/FAIL/ERROR 和 baseline/apply/target/regression 的日志及环境摘要。事务测试拒绝缺少回归、替换命令、错误 base/hash 的 PASS；模拟租约中断后接管仍使用同一 candidate，并拒绝旧 token，连续丢失 owner 三次后有界失败。这些测试不调用真实付费模型；实际原 graph integration 使用固定脚本模型。

## M5 结果查询

五个 Repair API 已实现：POST、list、detail、patch、artifacts。所有读取复用 session/用户归属，不存在或其他用户任务均 404。patch 尚未保存时 409 `patch_not_ready`；已有 patch 以原始字节返回，ETag 为保存的 SHA256，`X-Base-Commit` 为完整基准 SHA。

详情只返回 candidate metadata 和 validation summary，轮询不会下载完整 patch 或 validation logs。artifacts 按需读取验证 checks/manifest，全部日志输出总上限 64 KiB，包含 `truncated` 与 `stored_output_bytes`；不返回内部 Agent/Validator filesystem path。每个 fixture 最多 10 条固定 regression commands。新的 Artifact 测试与真实 API/worker integration 验证完整 PASS 的证据和原始 patch hash。完整 deadline/restart recovery 仍在 M5 实施中。

## M5 结果查询增量：2026-09-28

新增 GET patch/artifacts 与 task detail candidate/validation summaries。所有读取检查原用户归属；未生成补丁返回 409 patch_not_ready，已生成补丁返回原始 bytes（不通过 Unicode 重新编码），含 SHA ETag 与 exact base。artifact log 响应总上限 64 KiB，保存大小与读取截断标志明确。移除 detail RunView 的内部 Agent absolute path，artifact 不暴露 Validator path。轮询查询 candidate 仅 SQL metadata/octet_length，不取 patch；validation summary 使用 load_only，不取 logs/manifest。固定 regression 配置最多 10 条。没有声称进行过 EXPLAIN/性能实验。

实际相关 API/adapter integration：9 passed，9.61s，无 skip。测试验证未就绪/其他用户 404、原始非 UTF8 patch bytes/hash、中文日志有界截断和内部路径不泄露；真实原 Agent 完整链的 API 读取独立 PASS checks 与 patch SHA 匹配。Ruff/ty 通过。M5 IN PROGRESS；总 deadline、完整进程 restart 与不可恢复分类尚待实现，M6/M7 尚未实施。

补充匿名读取检查后，相关 Artifact 单项 1 passed（1.04s），detail/patch/artifacts 均 401；Ruff lint、28 个 repair/tests 文件格式、ty、121 个文档链接/围栏和 git diff-check 通过。

## M5 deadline 与 Runtime 停止增量：2026-09-28

新增 recovery_store、make-generated migration 0045、RepairRun runtime_stop_pending/error；dispatcher 在派发/观察前扫描 deadline 与持久停止意图。过期任务 TIMEOUT、清空旧执行/派发 token、保存已有候选和日志；执行租约即使 sweep 未运行也检查 task deadline。派发/验证整个过程有剩余总预算。停止采用真实 SDK interrupt + status observation；未知创建只查原 thread metadata、不重派发；deadline 后 60 秒仍未确认明确保存 unresolved/unconfirmed 并结束自动尝试。不能据此声称超时远程 shell 均被杀掉。

实际测试：

- 新 recovery + 受影响 API/dispatch/adapter/validation store：21 passed，15.12s，无 skip。真实 PG 执行 migration 0045；deadline 后旧 token 续租/checkpoint/failure 被拒绝，已有 validation 日志保留。
- 新增真实 active Runtime deadline interruption，相关 recovery：2 passed，2.09s。原 Graph 正在 running 时触发超时，之后实际 status interrupted，只有一个 Runtime Run，Task TIMEOUT 无候选。
- 加入 unknown create/missing thread 的真实查询及有界 unresolved 结果后，相关 recovery：3 passed，2.74s，无 skip；业务 attempt 仍 1，未创建第二个 Run。

M5 仍 IN PROGRESS：OS 级 worker crash/restart 和其余不可恢复分类/完整恢复矩阵尚待验收。当前修改未覆盖原云 Sandbox/完整 checkpoint resume，也未开发公共取消接口。

## M5 真实进程恢复与验收：2026-09-28

新增独立 test worker process，使用原 PG 隔离 schema/现有模型和原 SDK/Graph。实际 SIGKILL 后启动新 Python 进程：原 Runtime Run 已启动、Validator 执行中、远程 create 成功但尚未落库三个窗口。验证恢复真实等待 lease expiry，不通过改 DB 时间戳冒充等待。原 Run/candidate ID 与 hash 保持、Run history 一条、validation old ERROR/new PASS；新 worker 最终 COMPLETED。测试无付费模型。

实际执行（无 skip）：

- 初始 worker SIGKILL + replacement 单项：1 passed，2.87s；首轮已启动原 Run 后恢复。
- 增加 Validator 中途 SIGKILL，process 两项：2 passed，42.01s；包含实际 30 秒 execution lease 到期，same candidate 与两个独立 validation workspace。
- 新 Runtime missing/workspace loss/原 adapter：10 passed，14.00s；原工作区丢失时有候选则 COMPLETED，无候选则 agent_workspace_lost；404 runtime_missing，无重复 generation。
- 加入 dispatch attempt/status 查询、持久 queue wait/workspace/runtime/reconciliation events 后，API/dispatch/adapter/recovery：20 passed，18.49s。
- 远程 create→DB 存储窗口实际 SIGKILL 单项：1 passed，31.99s；replacement 查 metadata，attempt_count=1，RUNTIME_RECONCILED，history 一条。
- 加强第一进程测试，先实际观察 SDK pending/running 再 SIGKILL：1 passed，7.07s。

M5 最小范围 DONE，M6/M7 未完成。SIGKILL 不能执行 Python finally，可信本地执行可能残留目录/在途子进程；测试固定短时命令会退出并清理自己遗留目录，不宣称任意 Agent 后台 shell 均被杀掉。本版仍不覆盖完整云 Sandbox/全 checkpoint resume/Provider 容灾。

补充实际 candidate DELETE 拒绝与派发 event/attempt 关联检查：真实 adapter 单项 1 passed，2.46s；Ruff lint、32 个 repair/tests 文件格式、ty、121 个文档链接/围栏、baseline/tag/LICENSE/原 README/lock 与 git diff-check 通过。未提交/推送；sources 未修改。

## M6 React 两页增量：2026-09-28

实现 features/repair typed API、列表/表单、详情/diff/验证日志及 `/repair` 原文件路由；复用 session/原 Shell/query/UI components，原导航新增入口，原工具生成 routeTree。按需读取 patch/有界日志、错误/empty/loading、分页、network retry 同 payload/key、活动 REST polling（配置默认 4 秒）与 terminal stop。原同源 proxy 增 `/api/repair-tasks` 前缀。

环境安装使用 frozen pnpm lock，Node22.12.0/现有 pnpm11.19.0，1210 个包；首次大包下载超时退出，复用1209个缓存包并增加下载时限后安装成功。未改变 lock/package.json。原 packageManager 声明11.22.0，M7 新环境步骤须进一步固定并验证。

实际 checks：初始新组件 3 passed（0.835s），加入 terminal polling stop 后 4 passed（0.792s）；新增模块 oxlint 通过，oxfmt 已执行。完整 UI `tsc --noEmit` 首次有新增 section root 类型错误，已按原导航/location 类型扩展修复；修复后仍 8 个未改 upstream 文件的 fetch.preconnect / Ghostty platform 测试类型错误。通过 git archive 固定 baseline 的原 UI 快照、相同 node_modules 实际复现同样 8 个错误；typecheck 仍失败，不能标通过。

原 Vite production build 首次在 prerender 临时监听 ::1:3000 时受到 sandbox EPERM 而退出；允许本地临时服务后重新运行 build 成功（exit0），产物包含两页新路由。原 React Compiler 的 unsupported syntax/skipped optimization 警告仍存在。已启动该 production UI 在 loopback3010（原 Nitro server）。匿名 root Repair 请求在2030和3010得到相同 FastAPI404；2030是M0启动的 no-reload 原进程，尚未载入本轮新增 Repair 路由。这项代理读取不证明完整业务 UI/API 链；后续须重新启动匹配源码/迁移/fixture 的 Backend 并做实际 browser 验收。

M6 IN PROGRESS；M7 尚未实施。尚无浏览器截图/真实前端创建修复验收，不用组件 mock 或 build 来替代。

补跑受影响原 appLocation 测试与新 Repair 组件测试：2 files、18 tests passed（0.908s）；10 个修改 TS/TSX/config 文件格式检查、新 Repair 模块/routes lint、git diff-check 通过。Python/JS lock 均未变，当前 typecheck 仍上述 8 个真实失败，不标 M6 DONE。

## M6 actual browser acceptance and type compatibility — 2026-09-28

已解决上述 8 个类型问题：原 fetch timing/warmup wrapper 保留 runtime enumerable helper properties，callable input 不要求 SDK 闭包提供 Bun 的 helper；原 proxy test mock 保留真实 fetch helpers，Ghostty 测试 platform 采用真实 `Linux x86_64` 字面量。新增 meaningful fetch test 验证 helpers/body/timing。没有 Any/ts-ignore 或隐藏类型错误。

实际 `pnpm --dir ui run typecheck` exit 0；相关 fetchTiming/apiWarmup/surface/backend-proxy/RepairTasks：5 files/24 tests passed，1.02s；最新生产 build exit 0（原 React compiler unsupported-optimization warning 仍存在，非 build error）。后续未再跑全量 upstream suite。

启动当前源码的原 LangGraph test Server/FastAPI/Repair dispatcher（2031）与实际 Nitro production UI（3011），原 PostgreSQL 16.15，使用原 User/sign_in/issue_session。真实 Chrome 的 `playwright.repair.config.ts` 单项通过：POST202、真实原 Agent shell 修改、独立 checks exit `[1,0,0,0,0]`、PASS/COMPLETED、raw patch SHA256 与已存 candidate 一致、原 Runtime thread history 仅一条、返回列表同 task 显示 COMPLETED。

首次浏览器检查因 COMPLETED 在状态与 timeline 同时存在而 strict locator 失败，改为 role=status；随后真正链路通过。截图检查发现返回列表沿用原 QueryClient 30s freshness，Repair list 显式 staleTime=0，重新 build/restart UI 后实际复验：1 passed，6.6s。列表/详情/只读 diff/checks 截图在 ignored `.tools/repair-browser-artifacts/`，已实际查看；列表终态一致，补丁可读。不是静态 mock 页面，也没有付费 LLM。M6 DONE。

## M7 deployment implementation increment — 2026-09-28

新增三个服务的独立 Compose、固定 Python/uv/Node/pnpm Dockerfiles、private config/原用户+fixture/session bootstrap、typed browser helper、增量 Repair CI 和从零运行说明。原 Dockerfiles/Compose 保留；Docker context 新排除 `.tools`/`.langgraph_api`，私有 key/session 不进入 build context 或 Git。

配置生成实际执行，`.env.repair` 权限 600；Compose config --quiet exit 0。bootstrap 在现有 PG 实际执行，使用原认证生成允许用户和已知失败 fixture；其结果用于上述浏览器验收。Ruff/format/ty 的两个新 Python scripts 通过。

两次 Compose build 在官方 Docker Hub token/DNS 连接阶段超时，`auth.docker.io` 本机解析为 `157.240.10.41`，未下载/构建完基础镜像，尚无容器 healthy、新 volume 初始化或 Linux 新环境复跑证据。远程 GitHub Actions 尚未运行。Node22.12 上实际已用 pnpm11.19 完成 M6；固定 pnpm11.22 安装后报告要求 Node>=22.13，因此 M7 固定工具使用 Node24.13.1，另待实际验收。M7 IN PROGRESS，整个 MVP 未完成，不把 config 可解析当成部署通过。

随后在 ignored `.tools` 安装 Node24.13.1/pnpm11.22.0，实际 versions 确认，fixed tools 的 filtered frozen install exit 0（lock 未变）；完整 UI typecheck 通过。新 browser config/spec/helper strict tsc 首次发现 disconnected listener 的 Promise 参数类型错误，改为无参数 callback 后通过；oxlint 通过。6 个相关 UI files/38 tests passed（1.01s），固定 Node/pnpm 驱动真实 Chrome：1 passed（6.5s）。该验收仍是宿主机 services，不替代容器/新 volume 验收。

阶段收尾：34 个相关 Python 文件 Ruff/format/ty 通过，start script shell syntax 通过；workflow YAML 实际解析；私有 config 临时目录实验确认权限600、重复初始化拒绝且原内容不变；23 个文档/110 个本地链接与围栏检查通过；git diff-check 通过，LICENSE/Python/JS lock/packageManager 保留。新增文件已加入 intent-to-add 供 diff 审查，没有 commit/push。sources 未修改。

## M7 actual build and command evidence increment — 2026-09-28

只读检查确认本机已有 proxy7897 可达，Docker Hub token HTTP200；原 Docker proxy 未走通该路径，不修改全局设置。下载官方 crane v0.22.1 并校验官方发行 checksum，使用其经代理从官方 registry 拉取 linux/arm64 Python3.14.7/Node24.13.1/PostgreSQL16.15/uv0.12.19，实际 docker load 成功。Python 基础容器经 host.docker.internal proxy 对同一公开服务返回200。

实际 Compose build（不是 config 检查）进入 apt/pnpm/uv 安装。初次发现 pnpm patchedDependencies 必需的原 desktop patch 不在 build context，补充 COPY 后重新构建。uv 已识别 CPython3.14.7/locked197 packages；构建尚在执行，服务/新 volumes 仍未验收。

验收审查补强 demo fixture：固定基础 Python 真正绝对路径与 `-S`，不加载 Agent 可变包环境。新测试实际创建 Agent virtualenv 并写入可导入 package；受控 Validator 不可见该包，base-fail/patch-pass 正常。可信本地模式不能当对恶意 Agent 的隔离边界，复杂 fixture 必须独立配置受控依赖。

最初本地 Validator tests 暴露 git stderr/机器 stdout 混合：macOS diagnostic 污染 rev-parse SHA，13 tests 在 fixture setup 失败。修复 run_command 可分离 stderr 并并发有界 drain，git 返回纯 stdout、保留 error/diagnostic，不过滤警告假通过。新增真实 git wrapper 发出 diagnostic，机器输出仍正确，非零错误保留 stderr。相关 process/validation/candidate tests：23 passed、4 subtests passed（4.50s），Ruff/format/ty 通过。默认验证 logs 仍合并 stdout/stderr，原 output cap/timeout/child cleanup 语义保留。

## M7 final actual acceptance — 2026-09-28

网络链解决后实际 Docker Compose两个镜像build exit0。首次独立 volumes 的 PostgreSQL16.15（Debian/aarch64）、migration head14940cd67eb6、初始 repair_task count0；backend原API0.15.0rc5/runtime-inmem0.35.0rc5成功启动，backend/dashboard/postgres均running healthy。固定Python3.14.7/uv0.12.19/Node24.13.1/pnpm11.22.0/原锁文件；普通Docker/Local仍不是强隔离云Sandbox。

在实际backend容器执行 Repair相关范围 `pytest tests/repair`：58 passed、4 subtests passed，95.03s；JUnit报告tests62/failures0/errors0/skipped0，explicit no-skip检查通过。三个真实worker SIGKILL/30s租约等待包含其中；不是模拟进程crash或改DB时间。容器Ruff/format34 files/ty通过。宿主机Git解析变更后的PG/API/Adapter9 passed（12.49s）。测试耗时只是实际测试记录，不是修复性能benchmark。

新环境Chrome前端3012→API202→原2032Runtime/Agent实际修改→独立clean PASS→raw patch hash→单thread Runtime Run→列表COMPLETED：1 passed（7.2s），截图已实际查看。直接PG核对主环境Task/COMPLETED/Run/DISPATCHEDIntent/Candidate/PASSValidation各1条，hash与浏览器一致；原devsession工具已实际启动，没有公共登录绕过接口。

最后审查新增真实分页跨页/tie排序/owner隔离测试：宿主机PG1 passed（1.13s），重新打包backend source后Linux1 passed（0.89s）。普通backend重启保留原COMPLETED记录。最终Compose验证PATH仅基础系统目录，不含Agent virtualenv；fixture固定基础解释器真实路径/-S，实际检查服务uid1000、解释器owner0。对此配置相关Adapter/Validator/Process21 passed（7.65s），最终容器浏览器再次1 passed（8.1s）；没有重复跑不相关原全量suite。

**M0–M7/F01–F08 的 MVP-001 v1.0 可信本地范围 DONE**。逐项源代码/测试/运行对照见 [MVP_ACCEPTANCE](../architecture/MVP_ACCEPTANCE.md)。保留 LICENSE/remote/baseline/tag/原Python和JS lock，范围版本未改；README包含实际首启、私有开发登录、固定fixture、浏览器与相关测试命令、下载代理/重启/数据边界。远程GitHubActions未运行，未commit/push/创建PR；生产部署、完整Runtime crash/云恢复、真实模型修复效果和延期功能未作为完成能力。

最终补充默认浏览器验收：Playwright 自带 Chromium 实际运行通过（1 passed，7.4s）。随后移除浏览器请求和演示表单中专用测试 marker，约束留空；确定性模型仅在测试 seam 识别固定 arithmetic repair 输入，生产 Agent/输入转换未替换。重新构建 backend 后默认 Chromium 全链路再次通过（1 passed，6.0s，单项5.2s），记录 `.tools/repair-compose-no-marker-browser.log`。这证明普通固定 fixture 输入可运行，不要求用户知道测试 marker；仍不代表真实模型修复效果。

## R1 独立 Repair Worker — 2026-09-28

移除 FastAPI Repair lifespan，新增生产入口 `python -m agent.repair.worker` 与 JSON 关联日志；Compose四服务，backend仍承载原 Runtime。共用应用镜像与 /data 路径。实际 build/up通过；backend/dashboard/postgres healthy，Worker独立 running。

实际默认Chromium两项通过（14.8s）：停止Worker后API202/查询QUEUED，启动两个Worker后同任务COMPLETED，只有一个Runtime Run和候选；随后完整UI/patch/独立PASS链通过。Adapter/Dispatch/原三个SIGKILL子进程窗口12 passed（89.19s），无skip；报告`.tools/repair-worker-tests.log`、容器`/data/repair-worker-test-results.xml`与`.tools/repair-worker-browser.log`。未改DB时间假冒SIGKILL恢复；没有宣称容器级三个故障窗口或完整Runtime crash容灾。

相关Ruff/format/ty、浏览器strictTS检查通过；新原生命周期测试调整为独立Worker context，另有真实服务生命周期浏览器证明。上游第三方Python警告仍保留。R1 DONE；R2真实模型验收待配置与费用预算，尚无模型效果指标；远程CI未执行。

## R2 无费用样本准备 — 2026-09-28

新增 `scripts/repair_acceptance_fixtures.py`，实际生成10个不同合成小仓库，每个固定40位SHA。逐个执行baseline要求assertion failure，不接受import/setup错误；git检查/应用参考patch后target与regression均0，再恢复干净失败base。manifest在ignored `.tools/real-model-preparation-02/`，owner是准备占位UUID，没有提交RepairTask或模型调用；不把参考补丁通过当Agent成功率。

相关负例测试覆盖已有证据不可覆盖、baseline import错误不可当失败复现、错误参考补丁不可验收：3 passed。初次错误参考用与原代码相同内容，因空patch在apply阶段被拒绝，测试期望的错误阶段不匹配；改为有实际diff但仍错误的参考，实现真实target失败拒绝场景，复验通过。相关Ruff/format/ty与diff-check通过；记录`.tools/repair-acceptance-preparation-tests.log`及`repair-acceptance-preparation.log`。未运行全量upstream suite，未构建或启动真实模型环境。

验收文档已补R1 requirement/evidence对照及R2实验边界。正式R2仍待模型/凭据和明确费用上限；不得把这些无费用准备标成真实模型验收完成。
