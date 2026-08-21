# Dify 接入指南

## 1. 接入关系

FATHOM 作为工业数据、语义、本体、指标、权限和证据底座运行；Dify 通过自定义工具调用 FATHOM，不直接保存企业数据源凭证，也不负责计算指标口径。

本机已经将 FATHOM 注册到 Dify 的当前管理员工作区，工具提供方名称为“FATHOM 工业问数”。它是 OpenAPI 自定义工具，不是插件或应用，因此不会出现在插件市场或应用列表中。

## 2. 在本机找到已接入工具

1. 确认 Docker Desktop 与 FATHOM 均已启动。
2. 打开 `http://127.0.0.1`，登录本机 Dify。不要打开云端 Dify 地址。
3. 进入“工具”，切换到“自定义工具”区域。
4. 找到“FATHOM 工业问数”。

也可以直接打开：`http://127.0.0.1/tools`。

当前工具属于创建本机 Dify 时初始化的管理员工作区。若以后新增工作区，需要在目标工作区重新导入一次，因为 Dify 的自定义工具按工作区隔离。

## 3. 当前是如何导入的

导入源是：

```text
integrations/dify/fathom-openapi.yaml
```

Dify 读取该 OpenAPI 文件，以 `operationId` 生成工具定义，再把一个工具提供方和 5 个工具注册到当前工作区。当前本机导入通过 Dify 自身的工具管理服务完成，没有直接修改 Dify 数据库。

导入后生成：

| 工具 | 用途 |
| --- | --- |
| `search_semantics` | 搜索对象、指标、关系、事件和权限语义 |
| `ask_data` | 执行带 ONN、ABC、权限和证据的可信问数 |
| `search_enterprise_knowledge` | 检索内置与外接知识库并返回来源和相关度 |
| `get_object_context` | 读取对象属性和一跳关系上下文 |
| `run_controlled_agent_flow` | 执行可信问数、小白建模或受控诊断链路 |

## 4. 重新导入或导入到其他工作区

1. 启动 FATHOM，并监听 `0.0.0.0:8000`：

   ```powershell
   .\scripts\start.ps1 -BindAddress 0.0.0.0 -Port 8000
   ```

2. 在 FATHOM 的“数据接入 → 上层应用”中点击 Dify 卡片。系统会复制完整 OpenAPI 配置并打开 Dify 工具页。
3. 在目标 Dify 工作区进入“工具 → 自定义工具”。
4. 新建自定义工具，粘贴刚复制的 OpenAPI 内容；也可以使用页面下方的“下载工具配置”上传 YAML。
5. 工具名称填写“FATHOM 工业问数”。
6. 确认 Server URL 为：

   ```text
   http://host.docker.internal:8000/api/v1
   ```

7. 保存后应看到 5 个工具。

Dify 在 Docker 容器中运行，因此不能使用 `127.0.0.1:8000` 访问宿主机 FATHOM；必须使用 `host.docker.internal:8000`。

## 5. 在 Dify 中使用

### Workflow

1. 新建 Workflow。
2. 添加“工具”节点。
3. 选择“FATHOM 工业问数 / ask_data”。
4. 将用户输入映射到 `question`。
5. 将返回的 `answer` 输出给用户，并把 `trace_id` 保留在运行日志中。普通问数不需要填写对象、范围或其他参数。

### Agent

1. 新建 Agent 应用。
2. 在工具列表中启用需要的 FATHOM 工具。
3. 对普通问数优先启用 `search_semantics` 与 `ask_data`。
4. 需要对象关系上下文时启用 `get_object_context`。
5. 需要完整受控链路时启用 `run_controlled_agent_flow`。
6. 需要单独检索制度、手册或 SOP 时启用 `search_enterprise_knowledge`；`ask_data` 本身也会在无法形成指标计划时自动检索知识库。

建议在 Agent 指令中声明：数值问题必须调用 FATHOM 工具，不允许模型自行编造指标值。

## 6. 验证接入

先运行独立契约测试：

```powershell
.\.venv\Scripts\python.exe scripts\dify-contract-smoke.py --base-url http://127.0.0.1:8000
```

测试通过时会检查状态、答案、ABC 计划、证据与追踪 ID。

然后在 Dify 中调用 `ask_data`：

```json
{
  "question": "昨天 OEE 是多少？"
}
```

接入真实对象与观测数据后，FATHOM 会按名称、别名和权限自动识别可计算范围；无法唯一识别时返回自然语言澄清，不要求用户填写 `object_id`。

## 7. 常见问题

### 找不到“FATHOM 工业问数”

- 确认打开的是本机 `http://127.0.0.1`，不是云端服务。
- 确认位于“工具 → 自定义工具”，不是插件或应用页面。
- 确认当前工作区与导入时的工作区一致。
- 仍找不到时，按照第 4 节在当前工作区重新导入。

### 工具存在但调用失败

- 访问 `http://127.0.0.1:8000/api/v1/health`，确认 FATHOM 正常。
- 确认 OpenAPI 中使用 `host.docker.internal`，而不是容器内的 `127.0.0.1`。
- 运行第 6 节契约测试，先区分 FATHOM 问数问题和 Dify 编排问题。
- 生产环境启用认证后，在自定义工具凭证中配置 Bearer Token，不要把 Token 写进 Workflow 变量。
