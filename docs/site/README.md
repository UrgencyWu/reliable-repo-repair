# 静态介绍页

入口：[index.html](index.html)。这是独立的 HTML / CSS / JavaScript 页面，可由浏览器直接打开或通过静态服务预览。

## 本地预览

从仓库根目录启动只绑定本机的静态服务：

```bash
python3 -m http.server 4173 --bind 127.0.0.1
```

打开 `http://127.0.0.1:4173/docs/site/`。使用仓库根目录作为服务根，便于访问 README / 架构 / 许可链接。结束时按 Ctrl+C。

页面提供 PostgreSQL → Redis Stream → Worker → Runtime → 独立验证的数据流、五类消息故障恢复说明、派发/补丁/验证流程示例、截图切换和启动命令复制。截图来自本地 arithmetic fixture 演示。

## 文件

| 文件 | 用途 |
| --- | --- |
| `index.html` | 中文功能介绍、五服务数据流、故障恢复、实际截图、执行记录和启动入口 |
| `styles.css` | 桌面/移动端布局、键盘焦点、减少动态效果偏好 |
| `showcase.js` | 面板切换与命令复制 |
| `assets/overview.svg` | 展示 PostgreSQL / Redis 数据流的 README 横幅，原生 SVG |
| `assets/favicon.svg` | 本项目页面标识 |
| `assets/repair-list.png` | 既有本地任务列表验收截图 |
| `assets/repair-patch.png` | 既有本地补丁与独立验证验收截图 |

页面沿用 Open SWE 导航。

## GitHub Pages

[`showcase-pages.yml`](../../.github/workflows/showcase-pages.yml) 手动触发，打包此目录的 HTML / CSS / JS 与 `assets/` 并发布到 GitHub Pages。

发布构建把 `../../` 开头的源码链接绑定到当前 `GITHUB_REPOSITORY` 和 `GITHUB_SHA`，页面使用相对资源路径。部署到其他静态主机时，将源码链接替换为自己的仓库地址；可参考该 workflow 的打包步骤。GitHub 首次配置见 [发布指南](../OPEN_SOURCE_RELEASE.md)。

## 修改后的检查

- 检查新文案是否与源码和验收记录一致。
- 检查本地链接、图片、JS 语法，以及桌面/移动端是否溢出。
- 使用键盘操作面板切换与复制按钮，检查焦点和反馈。
- 验证 Pages 打包后的源码链接指向部署仓库，资源仍可在仓库子路径加载。
