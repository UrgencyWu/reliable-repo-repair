# Repair 本地部署与验收

Upstream baseline: `ad545353e2cdb4c7ae1c419f966c82436b63e799`。

本目录是可信本地开发/验收环境。原 FastAPI 与 LangGraph dev Runtime 保留在 backend；独立 repair-worker 负责派发、观察与 Validator，PostgreSQL 保存业务记录与派发意图，Redis Stream 传递待处理 Intent ID；React 生产构建通过原 Nitro 同源代理访问 API。五个容器：postgres、redis、backend、repair-worker、dashboard。

仅模型边界使用原测试 scripted model；原 Open SWE graph、Runtime、工具调用、独立工作区、补丁导出和 clean Validator 实际执行。没有真实 LLM 费用。这套演示入口不用于外部不可信仓库或生产部署；普通容器/Local Provider 不能当成强安全云 Sandbox。

## 首次启动

需要 Docker Compose v2、Python >=3.9（生成配置）、Node 24.13.1、pnpm 11.22.0（浏览器测试）。从仓库根目录执行：

```bash
python3 scripts/repair_init.py
docker compose --env-file .env.repair -f compose.repair.yaml up --build -d --wait --wait-timeout 180
```

脚本只在 `.env.repair` 不存在时创建随机数据库密码与 session 签名密钥，不输出凭证，文件权限 600。后续启动保留该文件，不重新生成。端口只绑定 loopback：UI `http://127.0.0.1:3012/repair`，Runtime/API `http://127.0.0.1:2032`。可在 `.env.repair` 修改端口。

backend 启动时运行原 migration，使用原 User/sign_in/session 格式初始化开发用户与已知失败的 arithmetic fixture。fixture 仅允许该用户，固定命令/patch 路径来自服务配置。浏览器通过下方私有 session 文件登录，未添加公共绕过认证的接口。

演示验证只需要 Python 标准库：固定基础解释器的真实绝对路径并使用 `-S` 排除 site-packages，命令不继承 Agent 的环境变量或激活其 virtualenv。验证 PATH 只包含基础系统工具目录，不含 Agent virtualenv bin。容器中的基础解释器/标准库/系统工具由 root 安装，Agent/Validator 使用非 root 用户；两者共享基础工具，但不加载 Agent 可变包环境。更复杂 fixture 必须配置独立受控工具/依赖环境，不能直接复用 Agent 安装结果；多平台/依赖安装矩阵仍延期。本地模式不是对恶意 Agent 的强隔离保证。

## 打开基本前端

```bash
npm install --global pnpm@11.22.0
pnpm install --frozen-lockfile --filter open-swe-dashboard... --filter open-swe --filter open-swe-e2e
pnpm --dir tests/e2e exec playwright install chromium
mkdir -p .tools/repair-demo
docker compose --env-file .env.repair -f compose.repair.yaml cp backend:/data/demo/session.json .tools/repair-demo/session.json
chmod 600 .tools/repair-demo/session.json
pnpm --dir tests/e2e exec node repair-tests/open-demo.mts
```

打开独立开发浏览器，自动使用原 session cookie 并填写 fixture/精确 SHA/固定失败命令；Constraints 可以留空，手动点击 Create task。测试模型根据结构化 Repair prompt 的 arithmetic fixture 选择脚本，用户无需填入测试 marker；故障测试的显式脚本选择仍保留在 test-only 边界。任务通过独立验证后显示 COMPLETED，进入详情查看只读 diff、timeline、Run 关联和 validation checks/logs。关闭浏览器结束 helper。

私有 session 不进入 Git、不分享。会话过期后重启 backend 并重新复制 session 文件；不会删除任务或改 fixture 的 base。环境重启前后的服务和数据库依赖保持一致。

## 实际自动验收

```bash
REPAIR_UI_URL=http://127.0.0.1:3012 REPAIR_RUNTIME_URL=http://127.0.0.1:2032 \
  pnpm --dir tests/e2e exec playwright test --config playwright.repair.config.ts
docker compose --env-file .env.repair -f compose.repair.yaml exec -T backend sh -ec '
  TEST_ANALYTICS_POSTGRES_URI="$POSTGRES_URI" REPAIR_TEST_RUNTIME_URL=http://127.0.0.1:2024 REPAIR_TEST_REDIS_URL="$REPAIR_REDIS_URL" \
    pytest tests/repair -q
'
```

测试仅运行 Repair 相关范围，不运行原项目全量测试；真实 PG/Runtime 配置缺失时的 skip 不作为通过。浏览器验证 POST 202→独立 PASS/COMPLETED→补丁字节/hash一致→原 Runtime history 一条→返回列表终态。实际结果和已知限制记录在 [VALIDATION](../../docs/upstream-analysis/VALIDATION.md)。

GitHub Actions 增量 [Repair MVP](../../.github/workflows/repair-mvp.yml) 使用相同 Compose、固定工具、类型检查、相关测试和浏览器链，拒绝 integration skip。该文件尚未在 GitHub 运行，不能用本地检查声称远程 CI 成功。

## 下载代理

正常联网环境直接按首次启动步骤执行。若仅构建中的 apt/npm/uv 需要本机已有代理，可显式传入临时 build args（端口按本机实际配置）：

```bash
REPAIR_BUILD_PROXY=http://host.docker.internal:7897
docker compose --env-file .env.repair -f compose.repair.yaml build \
  --build-arg HTTP_PROXY="$REPAIR_BUILD_PROXY" --build-arg HTTPS_PROXY="$REPAIR_BUILD_PROXY"
docker compose --env-file .env.repair -f compose.repair.yaml up -d --wait
```

这些 args 用于构建内部命令，不设置 Docker daemon 拉取 FROM 镜像的代理。镜像拉取需要 Docker 已有可用下载配置，或先经已有代理导入官方镜像。本次本机使用官方 [crane v0.22.1](https://github.com/google/go-containerregistry/releases/tag/v0.22.1)，官方 Darwin arm64 archive checksum `2231fc8df8806d20d680ff1225db44e095a55dd6ac1ae8eced4faf4b278b78fb`；`crane pull --platform linux/arm64 <官方 image:tag> <archive.tar>` 后 `docker load --input <archive.tar>`，再执行上述 build。未使用第三方替代镜像，未修改系统/Docker全局设置；crane 不是业务组件或正常联网环境的必需工具。

## 数据与重启边界

独立 named volumes 保存 PostgreSQL、Redis AOF、Agent/Validator workspace 和 dev Runtime `.langgraph_api` 文件；不复用原 `compose.yaml` 的数据库 volume。PostgreSQL 中的 Intent 是待派发事实来源；Worker 从中发布到 Redis Stream，消费者按 Intent ID 回查并持有数据库租约后才创建 Runtime Run。发布失败由数据库扫描重试；重复投递由租约和 Runtime 身份对账约束；待确认消息由 `XAUTOCLAIM` 接管；Stream 丢失后由数据库中的待处理 Intent 重建。Runtime 是原 dev/in-memory 实现，挂载其文件不等于 production checkpoint durability。最小 worker crash 恢复已有实际测试，完整 Runtime crash/云恢复仍不在本版。SIGKILL 可能遗留本地子进程/目录。

```bash
docker compose --env-file .env.repair -f compose.repair.yaml stop
docker compose --env-file .env.repair -f compose.repair.yaml start --wait
```

`down` 保留 volumes。仅当确定不要本演示环境的数据时使用 `down --volumes`；它会删除本环境数据库、workspace 与 Runtime 文件。

## 当前验证状态

**M7 DONE（可信本地范围）**。2026-09-28 两个镜像实际构建完成，全新 named volumes初始化、三个服务healthy；容器相关 Repair58 tests+4subtests 无skip，真实浏览器全链通过。新增稳定/隔离分页在Linux1 passed；最终基础工具PATH相关21 tests通过，浏览器复验1 passed。普通backend重启后已有完成结果保留。早期网络与patch context失败及修复保留在 [验证记录](../../docs/upstream-analysis/VALIDATION.md)，逐项证据见 [验收对照](../../docs/architecture/MVP_ACCEPTANCE.md)。没有生产/云恢复、真实模型成功率或远程CI已通过的声明。

## 独立 Worker 增量验收

历史四服务验收时，backend/postgres/dashboard healthy，独立 repair-worker running。当前 Compose 已增加 Redis 服务。Worker 本身未提供业务 healthcheck，运行效果通过真实任务验收。后台派发不依附 API lifespan；SIGTERM/SIGINT 取消本地 Worker 并关闭连接，远端 Agent 由接管/对账机制处理。

可独立停止 Worker、继续向 API 提交任务，再启动 Worker；可用 `up -d --scale repair-worker=2 repair-worker` 验证并发。API/Runtime 留在 backend；/data 共享卷与路径必须一致，不能直接推广为跨机器 Local Provider。

浏览器命令增加 `REPAIR_COMPOSE_ACCEPTANCE=1` 执行停 Worker 入队/双 Worker 唯一消费测试；不设置此变量时仅运行原浏览器链路并跳过服务控制测试。不要对其他运行中环境开启此变量。当前两项 Chromium 验收通过（14.8s）；相关 Adapter/Dispatch/三个 SIGKILL 子进程窗口12 passed（89.19s），无 skip。CI已加入变量，远程未运行。

## 2026-09-29 修复后部署验收

R1–R3 修复已重建至当前应用容器，2 项 Chromium 测试通过（16.0s，无 skip）。6 个原任务保留，2 个新增验收任务完成，单 Worker 运行，数据库卷未重建。详见 [部署验收记录](../../docs/reviews/DEPLOYMENT_ACCEPTANCE.md)。

## 2026-09-30 Redis Streams 增量验收

独立 PostgreSQL 16 与 Redis 7 容器中的 Stream、API、Dispatch 相关测试 19 passed，覆盖提交后发布失败、重复投递、消费后崩溃、消息接管、Stream 丢失后重建，以及发布标记与消费领取的行锁竞争。隔离的五服务 Compose 项目全部健康；Chromium 完整修复链路复跑 1 passed（6.3s），任务完成、独立验证 PASS、补丁字节哈希一致。详细故障窗口见 [验收对照](../../docs/architecture/MVP_ACCEPTANCE.md)。
