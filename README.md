# 渊渟 FATHOM 🌊

> 以 ONN 六元本体和 ABC 范式为核心的轻量工业数据智能底座。

FATHOM 将企业的对象、关系、属性、指标、事件和权限组织为可版本化语义契约，通过 `Acquire → Build → Compute` 受控执行链，为 Dify、BI、运营应用和其他 Agent 提供可信问数、分析、治理与工具调用能力。

## 当前能力

- ONN 六元本体：对象、关系、属性、指标、事件、权限。
- ABC 问数：对象获取、指标/关系构建、确定性计算与证据返回。
- 工业数据源：SQL、KV、图、时序、向量、文本，以及 TDengine、OPC UA、MQTT、Historian、文件和 REST。
- 语义资产：YAML 契约、版本、Owner、指标公式、关系图和权限策略。
- 工程工具：SQL 模板安全校验、语义导入导出、数据预检、一致性备份与保护性恢复。
- 开放能力：REST/OpenAPI；Dify Tool Plugin 与 MCP 适配接口按同一工具契约扩展。
- 模型网关：兼容主流云端与本地模型服务；自动获取模型并探测 Responses、Chat、Messages 和 Embedding 能力。
- 对话入口：多轮业务问答、语义证据、ABC 执行轨迹、建议追问与跨系统 trace_id。
- 智能体网络：12 个内置专职智能体，按可信问数、小白建模、实时诊断动态组成最短执行链。
- 通用 Agent 网关：OpenAPI 3.1、MCP Streamable HTTP、A2A Agent Card；适配 Dify、工作流平台与自研 Agent。
- Lite Profile：SQLite WAL、FTS5、可选 sqlite-vec、按需 DuckDB，无需 Docker。

## 技术栈

- 后端：Python 3.12、FastAPI、Pydantic、SQLAlchemy、DuckDB、sqlite-vec、sqlglot。
- 前端：Vue 3、TypeScript、Vite。
- 语义事实源：YAML + Git；运行状态与审计：SQLite。

## 本地运行（无 Docker）

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"

cd apps\web
pnpm install
pnpm build
cd ..\..

fathom init
fathom serve --host 127.0.0.1 --port 8000
```

打开 <http://127.0.0.1:8000>。生产运行只需要 Python；Vue 已构建为由 FastAPI 托管的静态资源。

运行配置可通过 Web“系统设置”、`config/fathom.yaml` 与 `FATHOM_*` 环境变量管理，
优先级为“环境变量 > YAML > Web 持久化 > 默认值”。API Key 只进入操作系统凭证库或
`env://VARIABLE` 引用，不写入 SQLite/YAML，也不从 API 回显。

开发前端：

```powershell
fathom serve
cd apps\web
pnpm dev
```

打开 <http://127.0.0.1:5173>，Vite 会把 `/api` 转发到 FastAPI。

## Dify 联调

FATHOM 自身无需 Docker；完整 Dify Community Edition 按官方方式使用 Docker Compose。
完整接入步骤见 [docs/Dify接入指南.md](docs/Dify接入指南.md)，本机运行说明见
[docs/DIFY-LOCAL.md](docs/DIFY-LOCAL.md)，OpenAPI 工具定义见 `integrations/dify/fathom-openapi.yaml`。

## 验证

```powershell
pytest
ruff check .
cd apps\web
pnpm typecheck
pnpm build
```

## 目录

```text
apps/api/       Python API、领域模型、执行与适配器
apps/web/       Vue Web 工作台
semantic/       ONN 语义契约事实源
config/         可复制的运行配置
docs/           架构与决策记录
data/           本地运行数据与备份（不提交 Git）
```

## 安全与准确率原则

- 上层模型不能直接获得数据库凭证，也不能执行任意 SQL。
- 语义不明确时澄清或拒答；只有通过对象、指标、权限和资源预算校验的计划才能执行。
- “99%”以已认证业务域的黄金问题集验收；确定性指标计算必须与基准 SQL 一致。
- 生产语义点击发布后自动执行回归评测；通过即发布，并保留审计和回滚点。
