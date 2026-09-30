# ADR-012: Reproducible trusted local Repair environment

Upstream baseline: `langchain-ai/open-swe@ad545353e2cdb4c7ae1c419f966c82436b63e799`。日期：2026-09-28。

## Status

Accepted and implemented for MVP trusted local deployment. 实际镜像 build/三个 healthy服务/新 volumes/Linux tests/browser 已通过；原始失败与修复过程保留如下，当前结论见 [验收对照](../architecture/MVP_ACCEPTANCE.md)，不由本 ADR 设计文字代替运行证据。

## Context

宿主机链路和真实浏览器已通过。其他开发者还需要不依赖当前机器目录、既有用户和测试数据库的启动方案；不能新增 OAuth 绕过接口，也不能把 paid model 当测试前置条件。原 production Dockerfile 使用另一个 API 版本/约束，不直接用于已审查的 dev Runtime 验收。

## Decision

新增独立 `compose.repair.yaml`，三个服务：PostgreSQL、原 LangGraph dev Server/FastAPI/嵌入式 Repair dispatcher、原 Dashboard 生产构建。保留原 Compose/Dockerfiles。用 upstream `uv.lock`/`pnpm-lock.yaml` 安装依赖，显式 Python 3.14.7、uv 0.12.19、Node 24.13.1、pnpm 11.22.0；PostgreSQL 16.15。基础镜像 tag 固定版本但不是 content digest；不宣称 bit-for-bit immutable image。

原 test graph 仅替换模型调用，复用真实 Agent。启动 CLI 使用原 migration/User.sign_in/issue_session，初始化专属可信 fixture 与私有 session 文件，签名 key/DB password 随机生成到 ignored `.env.repair`。浏览器 helper 使用原 cookie 格式；没有新公共登录接口/写入 API 特权。

测试模型按已渲染 Repair prompt/arithmetic fixture 自动选择脚本，正常创建不要求用户填写 E2E marker；专用故障测试显式 marker 的原选择行为保留。生产 adapter/prompt 不加入测试条件，也不修改原 Agent loop。

数据库、workspace、dev Runtime 文件使用本演示独立 volumes，服务非 root 执行，端口仅 loopback，Docker context 排除 `.tools` 和 Runtime 缓存。这里是可信容器内 Local Provider，不是强隔离 Sandbox，不运行不可信外部代码。dev Runtime 文件挂载不升级其恢复保证，完整 Runtime crash/production 持久化仍延期。

增量 CI 使用同一 Compose 和实际 Repair unit/integration/故障/browser 检查，拒绝 skipped integration。保留 upstream CI；不部署、不推镜像、不引入额外基础设施。

## Consequences

新环境能够独立初始化，并保留重启数据。首次构建需能访问官方镜像源和包仓库；实施初期 Docker Hub DNS/token 超时曾阻断验收，后来通过既有代理/官方镜像 cache解决。pnpm11.22.0 要求Node>=22.13，旧Node22.12.0/pnpm11.19.0不作为固定工具链；宿主机已另装固定工具，容器/CI显式指定符合版本。

后续切换真实模型或生产 Runtime 须单独审查配置/授权/持久化，不能直接复用测试模型凭证或本地开发登录。最终 M7 必须实际启动全新 volumes 并复跑完整浏览器与相关测试。

## Implementation evidence increment

本机现有 loopback HTTP proxy 实际返回 Docker Hub token HTTP200，容器经 `host.docker.internal` 访问同一路径也返回200。官方 google/go-containerregistry crane v0.22.1 发行包经官方 checksums 校验后，导入 Docker Hub 的 Python3.14.7/Node24.13.1/PostgreSQL16.15 与 GHCR uv0.12.19 官方镜像到本地 cache；未使用第三方镜像替换内容，未修改系统/Docker 全局代理设置。

实际 Compose build 暴露 pnpm patchedDependencies 引用原 `desktop/patches` 而 context 未复制，已在增量 UI Dockerfile 补齐；原 lock/patch 不修改。后续构建仍在执行，尚未作为 M7 完成证据。

演示 Validator 命令固定到基础解释器真实路径并使用 `-S`，不加载 Agent 可变 site-packages；容器基础解释器/stdlib root-owned，服务非 root。新增真实 virtualenv/package 污染测试证明 Agent 环境可导入的 package 不进入受控验证，独立 base-fail/patch-pass 仍成立。仅覆盖本版 stdlib fixture，不宣称任意依赖安装或恶意 Agent 的强隔离。

相关：[部署步骤](../../deploy/repair/README.md)、[ROADMAP](../ROADMAP.md)、[验证记录](../upstream-analysis/VALIDATION.md)。

## Final MVP validation

两个镜像实际 build成功；全新 PG16.15、migration head14940cd67eb6、初始RepairTask0、三个服务 healthy。容器实际58 Repair tests+4subtests 无失败/错误/skip，三个SIGKILL窗口包含其中；真实浏览器完整链通过。补充分页在Linux1 passed；最终验证PATH排除Agent virtualenv后相关21 passed，浏览器再次1 passed。普通backend重启保留已有COMPLETED。基础Python uid0、服务uid1000、stdlib/-S固定计划已检查。远程CI未运行，不写生产或完整Runtime crash保证。
