# 网页使用手册

登录后的每个功能页面都在右上角操作按钮下方显示“使用手册”。点击后在新标签页打开 `/assets/user-manual/index.html`，当前页面的表单内容保留。

网页版提供章节目录、关键词筛选、点击放大的截图及 Word 下载。手机上目录默认收起，表格在自身区域内横向滚动。

电脑端目录按第 1 至 16 章及管理员附录分组，同一章的节和小节收进可展开的子目录。支持全部展开或收起；滚动正文时自动标记当前阅读位置并展开对应分组，目录自身滚动，搜索框保留在侧栏上方。关键词搜索会展开相关结果，清空后恢复原有展开状态。

截图根据自身宽高比例设置展示尺寸：长截图限制高度并居中，横向截图使用正文宽度，始终保留原始比例和完整内容。点击截图可在页内放大、缩小、适应窗口或按原始尺寸查看；放大后滚动查看细节，按 Esc 或“关闭”返回正文。原图文件与 Word 下载不受显示调整影响。

## 更新内容

内容来源为 `outputs/manual/智能发布中枢系统用户使用手册_功能完善版_20261020.docx`。转换脚本只读取文件，不修改原文档；网页版与 Word 下载始终使用本次转换的同一个文件。

修改 Word 手册后，使用包含 `python-docx` 的 Python 环境运行：

```bash
python webapp/frontend/scripts/build-user-manual.py
```

也可以显式指定其他版本的 Word 文件：

```bash
python webapp/frontend/scripts/build-user-manual.py /绝对路径/使用手册.docx
```

生成的 HTML、截图和下载文件位于 `webapp/frontend/public/assets/user-manual/`。页面样式与搜索逻辑分别在同目录的 `manual.css`、`manual.js` 中维护。

随后执行前端构建，并按现有流程部署完整 `webapp/frontend/dist/`：

```bash
cd webapp/frontend
corepack pnpm run build
```

Vite 会复制这些静态文件；生产环境复用 FastAPI 已有的 `/assets` 路由，无需新增接口。手册属于静态帮助内容，页面及 Word 下载可以通过其 URL 直接访问。
