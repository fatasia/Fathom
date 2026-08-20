# 通用 Agent Access Gateway

平台适配器不得复制业务逻辑。OpenAPI、MCP、A2A 和后续 SDK 均调用相同的查询服务、语义仓库、权限校验和证据链。

## 已实现

- OpenAPI 3.1 / REST：适用于 Dify、HTTP 工作流平台和自研系统。
- MCP `2025-11-25`：`POST /mcp`，无状态 Streamable HTTP JSON 模式，提供 tools 与 resources。
- A2A `0.3.0` 发现：`GET /.well-known/agent-card.json`；任务交换仍标记为后续能力，避免宣称虚假兼容。
- 能力清单：`GET /api/v1/agent-gateway/capabilities`。

MCP 当前工具：

- `fathom.ask_data`：受 ONN / ABC 约束的工业问数。
- `fathom.search_semantics`：对象、关系、属性、指标、事件与权限检索。

资源：`fathom://semantics/overview`。

## 统一控制面

所有入口必须传递最终用户身份、Workspace、对象范围和 trace context，并共享以下门禁：身份范围、本体校验、指标认证、资源预算、证据和 trace_id。生产部署还应启用 OAuth 2.1/OIDC、mTLS 或短期 Subject Token，以及 Origin 校验、速率限制和审计。
