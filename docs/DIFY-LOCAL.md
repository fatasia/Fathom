# Dify 本机联调

FATHOM 本体、语义、权限和数据源均独立运行；Dify 只作为上层 Agent / Workflow 消费
FATHOM 的受控工具，不保存企业事实源凭证。

## 固定版本

- Dify Community Edition：`1.16.1`
- 本机源码目录：`tools/dify`（已加入 `.gitignore`）
- 官方完整运行方式：Docker Compose

## 启动

Docker Desktop 首次安装后需要启动并等待 Engine Ready，然后执行：

```powershell
.\scripts\dify-local.ps1 -Action up
.\scripts\dify-local.ps1 -Action status
```

打开 `http://localhost/install` 完成管理员初始化。FATHOM 默认运行于
`http://host.docker.internal:8000`（从 Dify 容器访问宿主机）。

## 导入 FATHOM 工具

在 Dify 的“工具 → 自定义工具 → 导入 OpenAPI”中导入：

`integrations/dify/fathom-openapi.yaml`

联调前可独立运行：

```powershell
.\.venv\Scripts\python.exe scripts/dify-contract-smoke.py
```

测试覆盖问数状态、ABC 计划、证据、追踪 ID 和 OpenAPI 路径，不需要先创建 Dify 应用。
