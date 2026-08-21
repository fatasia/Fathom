# 渊渟 FATHOM 🌊

轻量工业数据语义与智能体底座：用 ONN 组织对象、关系、属性、指标、事件和权限，用 `Acquire → Build → Compute` 将自然语言编译成可校验、可计算、可追踪的执行计划。

## 核心能力

- 可信问数：流式回答、Markdown、附件、会话历史、ABC 过程、证据和 trace。
- 业务语义：对象网络、指标口径、版本、Owner、权限、候选、发布和回滚。
- 数据接入：关系数据库、文件、REST、TDengine、MQTT、OPC UA、KV、全文、图和向量。
- 知识库：轻量内置文档库和通用外接检索。
- 工程工具：SQL 模板、轻量管道、Python 扩展、导入导出、备份恢复。
- 受控演化：Schema 发现、语义候选、黄金问题集、冲突检查和发布门禁。
- 开放接入：REST/OpenAPI、SSE、MCP 和 A2A。

## 快速启动

Windows：

```powershell
Set-ExecutionPolicy -Scope Process Bypass
Copy-Item config\fathom.example.yaml config\fathom.yaml
.\scripts\install.ps1 -LiteOnly
.\scripts\start.ps1 -BindAddress 0.0.0.0 -Port 8000
```

打开 <http://127.0.0.1:8000>。需要全部连接器时执行 `.\scripts\install.ps1`。

部署包已包含编译后的 Web 页面。运行时数据库、密钥和本地数据不进入代码包；首次启动会自动创建空数据库。

## 验证

```powershell
.\.venv\Scripts\python.exe -m ruff check apps/api/src apps/api/tests
.\.venv\Scripts\python.exe -m pytest -q
pnpm --dir apps/web build
```

## 文档

- [部署与接入指南](docs/部署与接入指南.md)：运行、部署、项目与模型配置、数据源、Dify 和其他平台接入。
- [使用手册](docs/使用手册.md)：按真实页面说明问数、建模、知识、工程、治理和日常验收。
- [架构设计](docs/架构设计.md)：整体架构、ONN、ABC、智能体网络、轻量存储、自进化和安全控制。

## 目录

```text
apps/api/       Python API、领域服务、执行与适配器
apps/web/       Vue Web 工作台
semantic/       ONN 语义契约
config/         运行配置示例
integrations/   上层平台接入契约
docs/           三份正式文档及其图片资源
scripts/        安装、启动、验证与打包脚本
data/           本地运行数据库和备份，不进入发布包
```

## 准确率边界

“99%”只表示指定业务域、指定黄金问题集、指定语义和模型版本下的评测结果，不代表任意企业问题。企业数值必须来自真实数据和已发布确定性口径；未知、越权或缺少事实的问题在执行前澄清或阻断。
