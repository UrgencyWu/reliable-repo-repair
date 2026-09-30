# 修复后部署验收

日期：2026-09-29。基线：Open SWE ad545353e2cdb4c7ae1c419f966c82436b63e799。

## 结果

R1–R3 修复已进入当前本地 Compose 部署，两个实际 Chromium 验收 **2 passed，16.0s，无 skip**。

1. Worker 停止期间 API 接受请求（202），任务保持 QUEUED；启动两个 Worker 后完成任务，验证唯一执行，并恢复单 Worker。
2. 浏览器创建任务，经原 Open SWE/LangGraph（确定性模型）、工具执行、候选导出、独立 checkout 验证，最终显示 COMPLETED、PASS、patch；核对 patch 字节 SHA256 与持久化结果一致，Runtime history 只有一个 Run，返回列表显示终态。

部署前 6 个任务全部 COMPLETED、无 pending stop。部署后原 6 个任务 ID 全部保留，新增 2 个验收任务均 COMPLETED，总计 8 个，pending stop 仍为 0。PostgreSQL 原容器及数据卷保留，没有执行 down 或删除 volumes。

## 实施

使用现有私有 `.env.repair`，未重建凭据。重新构建 backend/repair-worker/dashboard，再以 `up -d --no-build --wait` 更新应用。backend 与 repair-worker 使用更新后的同一镜像。实际比较两个运行容器内 dispatch.py、dispatch_store.py、execution_store.py 与工作区 SHA256，三处修复模块完全一致。

最终 backend/postgres/dashboard healthy；repair-worker running、单实例。Worker 没有业务 healthcheck，执行能力由上述任务验收证明。

```sh
docker compose --env-file .env.repair -f compose.repair.yaml build backend repair-worker dashboard
docker compose --env-file .env.repair -f compose.repair.yaml up -d --no-build --wait --wait-timeout 180 backend repair-worker dashboard
REPAIR_UI_URL=http://127.0.0.1:3012 REPAIR_RUNTIME_URL=http://127.0.0.1:2032 REPAIR_COMPOSE_ACCEPTANCE=1 pnpm --dir tests/e2e exec playwright test --config playwright.repair.config.ts
```

测试前从 backend 复制最新私有 session 到既有 `.tools/repair-demo/session.json`，保持权限 600，不输出或提交 cookie。测试使用项目固定 Node/pnpm。

本地证据：`.tools/deploy-rebuild.log`、`deploy-update.log`、`deploy-acceptance.log`、`deploy-source-hashes.json`、部署前后 task ID 清单，以及 `.tools/repair-browser-artifacts` 下浏览器截图。构建有大 chunk 提示，浏览器测试有颜色环境变量 warning；无构建或验收失败。

## 边界

这是可信本地 Compose 的更新部署与冒烟验收，不是生产部署、安全隔离或真实模型成功率验证。本轮没有重复执行全量测试；R1–R3 边界回归与 SIGKILL 结果见 [修复记录](FIX_RESULTS.md)。没有为部署增加业务功能。
