# 参与贡献 FATHOM

感谢你愿意参与渊渟 FATHOM。本文说明如何搭建开发环境、提交前必须通过的验证、提交与 PR 约定，
以及新增语义契约的要求。提交代码即表示你同意以 MIT 协议（见 [LICENSE](LICENSE)）授权你的贡献，
并遵守[行为准则](CODE_OF_CONDUCT.md)。

## 环境要求

| 组件 | 版本 | 说明 |
|---|---|---|
| Python | 3.12 及以上 | `pyproject.toml` 中 `requires-python = ">=3.12"` |
| Node.js | 20 及以上 | 前端构建与工具链 |
| pnpm | 11.x | 仓库通过 `packageManager: pnpm@11.19.0` 固定版本 |
| Git | 任意较新版本 | Windows 建议关闭 `core.autocrlf`，仓库已用 `.gitattributes` 归一化换行 |

外部数据库、消息中间件等连接器依赖不是开发必需项，按需安装即可。

## 获取代码并安装

### Windows（推荐：安装脚本）

```powershell
git clone https://github.com/fatasia/Fathom.git
cd Fathom
Set-ExecutionPolicy -Scope Process Bypass
Copy-Item config\fathom.example.yaml config\fathom.yaml
.\scripts\install.ps1 -LiteOnly
.\scripts\start.ps1 -BindAddress 0.0.0.0 -Port 8000
```

`Set-ExecutionPolicy -Scope Process Bypass` 只对当前 PowerShell 会话生效，退出即失效，不会改动机器级策略。

`scripts\install.ps1` 会创建 `.venv`、以 `pip install -e '.[dev]'` 安装后端、在 `apps/web` 执行
`pnpm install` 与 `pnpm build`，最后运行 `fathom init` 初始化本地 `data/` 目录。

需要 SQL（Oracle/PostgreSQL/MySQL/SQL Server）、工业（OPC UA/MQTT/TDengine）与上下文
（Elasticsearch/Neo4j/Qdrant/Redis）等全部连接器时，去掉 `-LiteOnly`：

```powershell
.\scripts\install.ps1
```

### 手动安装（跨平台）

```bash
git clone https://github.com/fatasia/Fathom.git
cd Fathom
python -m venv .venv

# Windows
.venv\Scripts\python.exe -m pip install -e '.[dev]'
# macOS / Linux
./.venv/bin/python -m pip install -e '.[dev]'

pnpm --dir apps/web install
```

需要全部连接器时，把 `.[dev]` 换成 `.[dev,connectors-sql,connectors-industrial,connectors-context]`。

安装完成后初始化本地数据目录并启动：

```bash
python -m fathom.cli init
python -m fathom.cli serve --host 127.0.0.1 --port 8000
```

Web 工作台地址为 <http://127.0.0.1:8000>。

想直接看到数据，可以载入仓库自带的示例数据集并运行认证评测：

```bash
python -m fathom.cli demo-init
python -m fathom.cli eval
```

`demo-init` 只写入带 `demo.manufacturing` 标记的示例事实（`--status` 查看状态，`--reset` 重建）；
`eval` 运行 `seed/golden-questions.yaml` 的四道门禁，未全过会以非零码退出。
涉及语义契约或评测的改动，请在 PR 描述里附上 `fathom eval` 的输出。

## 提交前验证

以下三条命令必须全部通过，CI 与评审会以同样的口径检查：

```bash
python -m ruff check apps/api/src apps/api/tests
python -m pytest -q
pnpm --dir apps/web build
```

- `ruff` 配置见 `pyproject.toml` 的 `[tool.ruff]`，规则集为 `E, F, I, UP, B, SIM`。
- `pytest` 的 `testpaths` 为 `apps/api/tests`，`pythonpath` 为 `apps/api/src`，无需额外设置环境变量。
- 前端构建包含 `vue-tsc -b` 类型检查，类型错误会让构建失败。

只改前端时至少要跑 `pnpm --dir apps/web build`；改动后端或语义契约时必须同时跑 `ruff` 与 `pytest`。

## 提交信息约定

仓库使用 Conventional Commits 前缀，与现有历史保持一致（`git log --oneline` 可查看）：

| 前缀 | 用途 |
|---|---|
| `feat:` | 新增能力、新增语义资产、新增接口 |
| `fix:` | 修正缺陷、修正错误的映射或配置 |
| `docs:` | 文档、ADR、注释、示例 |
| `chore:` | 构建、依赖、忽略规则、发布打包等无行为变更的改动 |

示例：

```text
feat: add shift dimension to manufacturing execution metrics
fix: reject semantic plans with unbound dimensions
docs: add contributing and security policies
chore: ignore generated release packages
```

要求：

- 一行主题，动宾结构，不加句号，长度不超过 72 字符；需要展开说明时空一行后写正文。
- 一次提交只做一件事。把格式化、改名与功能改动混在一起会让评审无法看清行为变化。
- 不要把生成的产物提交进仓库：`.venv/`、`apps/web/dist/`、`apps/web/node_modules/`、
  `apps/api/src/fathom/interfaces/static/`、`data/*.db`、`artifacts/`、`dist/` 已在 `.gitignore` 中排除。

## 分支与 PR 流程

1. 从 `master` 开出短生命周期分支，命名建议 `feat/<主题>`、`fix/<主题>`、`docs/<主题>`。
2. 在分支上完成改动并本地跑通上文三条验证命令。
3. 推送分支并向 `master` 发起 Pull Request，按 `.github/PULL_REQUEST_TEMPLATE.md` 填写变更目的与验证方式。
4. 保持改动聚焦；评审提出修改后以追加提交响应，不要强制推送覆盖历史，便于对比。
5. 合并通常使用压缩合并（squash），因此主题行要能独立表达这次改动。
6. 涉及语义契约、执行计划、策略执行点或执行收据的改动，需要在描述里说明兼容性与影响面；
   若是架构级决策，先在 `docs/adr/` 增加 ADR 再改代码。

不要直接向 `master` 推送。

## 代码风格

### Python

- 目标版本 Python 3.12+，使用 `from __future__ import annotations` 延迟注解求值。
- ruff `line-length = 100`，请让行长控制在 100 字符内，不要用 noqa 规避。
- 全部公开函数、方法必须写类型注解；返回值与参数类型明确，避免裸 `Any`。
- 配置与外部数据模型使用 pydantic（`BaseModel` / `pydantic-settings`），让非法输入在边界处被拒绝，
  而不是在深层逻辑里靠 `if` 兜底。
- 应用服务按职责分层：`apps/api/src/fathom/application/` 放领域服务，
  `adapters/storage/` 放持久化，`interfaces/` 放 HTTP/MCP/A2A 入口，`domains/` 放领域模型。
  不要让适配层依赖接口层。
- 任何对外部数据源的执行都必须经过物理计划器与策略执行点，只允许参数化只读 SQL；
  不要在连接器里拼接字符串。参见 `docs/adr/0002-central-policy-enforcement.md`。

### Vue 与 TypeScript

- Vue 3 组合式 API 与 `<script setup>`；类型定义不写 `any`。
- 组件内不直接拼接后端 URL，统一走现有请求封装。
- 新增用户可见文案使用中文，与现有界面保持一致。

### 通用

- 不要在代码、配置、示例或文档里写入任何真实凭证、内网地址、客户名称。
  凭证只通过环境变量或 `secret_reference` 提供，参见 [SECURITY.md](SECURITY.md)。
- 提交前删除调试输出与临时文件。

## 如何新增语义契约

语义契约是语义层的载体，放在仓库根目录的 `semantic/` 下，一个业务域一个 YAML 文件。
请以 `semantic/manufacturing.execution.yaml` 为模板。

顶层字段：

```yaml
name: manufacturing_execution      # 契约标识，通常与文件名一致
label: 制造执行语义域               # 中文名称，会出现在界面上
version: 0.1.0                    # 语义版本，发布与回滚按此对齐
domain: manufacturing.execution    # 业务域点分标识
owner: production-excellence       # 资产责任人
```

`assets` 列表按 `kind` 组织资产，每种 `kind` 字段要求不同：

| kind | 关键字段 | 说明 |
|---|---|---|
| `object` | `key` `label` `description` `domain` `owner` `aliases` | 业务对象，如工厂、产线、设备、工单 |
| `attribute` | 同上 | 对象上的稳定属性，如产线编码 |
| `relation` | 同上 | 对象之间的关系 |
| `metric` | 另加 `source` `unit` `dimensions` `expression` | 指标口径，`source` 指向物理表，`expression` 是确定性口径 |
| `event` | 另加 `source` | 带时间与上下文的事件，如设备停机 |
| `policy` | 无额外字段 | 授权口径，如按工厂/产线/指标授权只读查询 |

`relations` 顶层列表描述对象间的连通关系，需要 `key` `label` `source_object` `target_object`
`cardinality`（`one_to_many` / `many_to_one` 等）与 `description`。

新增契约的检查清单：

1. `key` 在整个文件内唯一，使用小写下划线命名；`label` 与 `description` 用中文，说明业务含义而非技术实现。
2. `aliases` 填写业务人员的真实说法（如「达成率」「计划达成率」），评测会遍历全部别名 × 全部句式。
3. 指标必须有明确的 `unit`、`dimensions` 和可计算的 `expression`；口径不确定的指标不要写进去，
   宁缺勿滥——未知指标在执行前会被澄清或阻断。
4. 完成契约后，在 `seed/demo-dataset.yaml` 补上对应的最小事实集，并在
   `seed/golden-questions.yaml` 增加别名与 `expected_value`。两个文件中的
   `expected_value` 与观测值必须严格一致，否则确定性执行门禁会失败。
5. 本地验证：

   ```bash
   python -m fathom.cli init
   python -m ruff check apps/api/src apps/api/tests
   python -m pytest -q
   ```

   仓库自带的 `apps/api/tests/test_accuracy_gate.py` 会覆盖黄金问题集的确定性执行门禁。
6. 在 PR 描述中说明新契约的业务域、责任人和评测结果。语义契约的版本与发布门禁由 `/api/v1/` 下的
   治理接口管理，请勿手工改动已发布版本的历史记录。

## 报告问题

- 缺陷与功能建议：使用 `.github/ISSUE_TEMPLATE/` 下的模板。
- 安全漏洞：不要开公开 issue，按 [SECURITY.md](SECURITY.md) 的渠道私下报告。
- 行为准则问题：按 [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) 的联系方式反馈。