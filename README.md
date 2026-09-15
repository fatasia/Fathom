# 渊渟 FATHOM 🌊

轻量数据语义与智能体底座：用统一语义层组织对象、关系、属性、指标、事件和权限，把自然语言编译成可校验、可计算、可追踪的执行计划。

![FATHOM 系统总体架构](docs/assets/diagrams/fathom-system-architecture-v2.png)

## 核心能力

- 可信问数：自然语言只绑定语义，MQL 通过口径、维度和权限校验后由固定模板执行。
- 业务语义：对象网络、指标口径、版本、Owner、权限、候选、发布和回滚。
- 数据接入：关系数据库、文件、REST、TDengine、MQTT、OPC UA、KV、全文、图和向量。
- 知识库：轻量内置文档库、通用外接检索，以及导入时一次性语义提炼。
- 工程工具：SQL 模板、轻量管道、Python 扩展、导入导出、备份恢复。
- 受控演化：Schema 快照与变更识别、评审候选、黄金问题集、冲突检查和发布门禁。
- 语义运行时：版本化物理映射、多源路由、PostgreSQL/SQLite 只读执行、统一策略、质量契约、运行血缘和执行收据。
- 反馈与诊断：内置界面和 Dify 点赞/点踩、显式纠正情绪识别、证据阶梯式根因分析。
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

### 载入示例数据

仓库自带一套示例语义域与事实数据，clone 之后无需修改任何文件即可体验问数、语义运行时与评测：

```powershell
.\.venv\Scripts\python.exe -m fathom.cli demo-init
.\.venv\Scripts\python.exe -m fathom.cli eval
```

`demo-init` 只写入带 `demo.manufacturing` 标记的示例事实，不会触碰你已有的数据源、会话与凭证；`--status` 查看当前状态，`--reset` 先清除再重建。`eval` 会运行黄金问题集认证评测，四道门禁（语义规划、确定性数值、证据完整、安全拒答）全部通过才算达标。

示例资产都是可编辑的普通文件，替换成你自己的即可：

| 文件 | 作用 |
| --- | --- |
| `semantic/manufacturing.execution.yaml` | 示例语义契约：对象、指标、事件、权限与关系 |
| `seed/golden-questions.yaml` | 黄金问题集：指标别名、问题句式、安全拒答用例与基准值 |
| `seed/demo-dataset.yaml` | 示例事实数据，日期用相对偏移，clone 到任何时间都能直接用 |

`seed/golden-questions.yaml` 里每个指标的 `expected_value` 必须与 `seed/demo-dataset.yaml` 中该指标「昨天」的观测值一致，否则确定性数值门禁会失败。

### 本机 PostgreSQL 运行时演示

凭证只通过当前进程环境变量提供，不写入仓库：

```powershell
$env:FATHOM_DEMO_PG_PASSWORD = '<your-password>'
$env:PYTHONPATH = 'apps/api/src'
..venv\Scripts\python.exe scripts\seed-semantic-runtime-demo.py
..venv\Scripts\python.exe scripts\configure-semantic-runtime-demo.py
```

脚本只创建/更新独立的 `fathom_p0p3_demo` schema，并配置 5 个指标映射、质量契约及 20 个运行时黄金问题。启动 FATHOM 时需要继续提供同名环境变量。

## 验证

```powershell
.\.venv\Scripts\python.exe -m ruff check apps/api/src apps/api/tests
.\.venv\Scripts\python.exe -m pytest -q
pnpm --dir apps/web build
```

## 文档

- [部署与接入指南](docs/部署与接入指南.md)：运行、部署、项目与模型配置、数据源，以及接入 Dify 和其他平台。
- [使用手册](docs/使用手册.md)：按真实页面说明问数、建模、知识、工程、治理和日常验收。
- [架构设计](docs/架构设计.md)：整体架构、语义层、计划编译与执行、智能体网络、轻量存储、自进化和安全控制。

## 目录

```text
apps/api/       Python API、领域服务、执行与适配器
apps/web/       Vue Web 工作台
semantic/       语义契约
seed/           示例数据集与黄金问题集
config/         运行配置示例
integrations/   上层平台接入契约（含 Dify 工具与 Chatflow）
docs/           正式文档、架构图与截图资源
scripts/        安装、启动、验证与打包脚本
data/           本地运行数据库和备份，不进入发布包
```

## 许可

本项目采用 [MIT 许可](LICENSE)。