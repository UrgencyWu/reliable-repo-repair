# GitHub 开源展示与发布

本指南介绍仓库上传、GitHub 展示信息与 HTML 页面发布。项目功能、启动方式和来源说明见 [README](../README.md)。沿用现有 Open SWE Git 历史，以 `upstream` 跟踪上游，以 `origin` 发布自己的仓库。

## 仓库信息

仓库名可使用 `reliable-repo-repair`，显示标题为 **Reliable Repo Repair**。

About 描述可直接复制：

> Repository repair with PostgreSQL-backed tasks, Redis Streams delivery, a standalone Worker, immutable patches, and independent validation.

Topics：`open-swe`、`ai-agent`、`repository-repair`、`langgraph`、`fastapi`、`postgresql`、`redis`、`python`、`typescript`、`docker-compose`。

发布 Pages 后，将 workflow 返回的 URL 填到 About 的 Website。

## 首次上传

在 GitHub 自己的账户下创建空仓库，不额外生成 README / LICENSE / .gitignore，避免与保留的历史冲突。保留 `upstream`，将自己的仓库配置为 `origin`。以下命令中的地址应先替换为自己的真实地址：

```bash
git status --short
git remote -v
git remote add origin https://github.com/YOUR_ACCOUNT/YOUR_REPOSITORY.git
```

已有 `origin` 时核对其地址。首次发布应将业务代码、迁移、测试、部署配置与展示文件一起纳入提交。

```bash
# 检查工作区与暂存区，再纳入准备公开的项目文件
git diff --stat
git diff --cached --stat
git add -A
git diff --cached --stat
git diff --cached --check
git commit -m "feat(repair): publish reliable repository repair system"
# 将当前提交上传到新建仓库的 main 分支
git push -u origin HEAD:main
```

`HEAD:main` 将当前提交上传为新仓库的 main，保留本地分支名与现有 Git 历史。若目标仓库已有历史，先 fetch 并完成合并。

`.env.repair`、`.tools/`、session、virtualenv、node_modules 和测试产物由现有 `.gitignore` 排除。提交前检查暂存内容，私有凭据保存在本地。可用以下命令确认忽略规则：

```bash
git check-ignore .env.repair .tools/repair-demo/session.json
```

随仓库发布 [LICENSE](../LICENSE)、[ATTRIBUTION](../ATTRIBUTION.md)、[原 README](upstream-analysis/UPSTREAM_README.md) 和第三方许可。

## 发布 HTML 介绍页

介绍页位于 [`docs/site/index.html`](site/index.html)。它可以独立于业务系统发布，不需要数据库、模型 key、Docker 或前端打包。

1. 将含 `.github/workflows/showcase-pages.yml` 的提交推送到自己的仓库默认分支。
2. 在 **Settings → Pages → Build and deployment → Source** 选择 **GitHub Actions**。
3. 在 **Actions → Publish project showcase → Run workflow** 选择默认分支，手动运行。
4. 成功后从 `github-pages` environment 或任务输出打开网页，将其 URL 填入 About 的 Website。

GitHub Pages 的权限、artifact 与 environment 配置依据 [GitHub 官方自定义 workflow 文档](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages)。workflow 默认不监听 push，后续每次更新由维护者手动发布；发布范围仅为静态介绍页资源。

构建会自动把 README、架构、贡献、许可等链接指向本次提交所在的仓库。页面资源为相对路径，支持 `https://ACCOUNT.github.io/REPOSITORY/` 项目站点。

## 持续维护

展示材料围绕功能、架构、执行流程与使用方式组织。更新时同步维护 README、页面文案与截图。
