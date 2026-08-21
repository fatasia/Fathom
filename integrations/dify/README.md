# Dify 接入 FATHOM

FATHOM 管理数据源、ONN 语义、指标口径、权限和执行；Dify 管理模型、Prompt、Workflow、Agent 与应用发布。Dify 不保存数据库凭证，也不执行任意 SQL。

## 方式一：Custom Tool / OpenAPI

1. 启动 FATHOM Web 服务。
2. 在 Dify 的“工具 → 自定义工具”中导入 `fathom-openapi.yaml`。
3. 将 Server URL 改为 Dify 服务能够访问的 FATHOM 地址。
4. 为工具凭证配置服务端 API Token；不要把 Token 写进 Workflow 参数。
5. 在 Workflow 或 Agent 中使用语义搜索、可信问数、对象上下文或受控智能体链路。
6. 将 FATHOM 返回的 `trace_id` 保存到 Dify 运行日志，支持跨系统追踪。

## 方式二：HTTP Request

快速验证时，使用 HTTP Request 节点调用：

```http
POST /api/v1/query/ask
Content-Type: application/json

{
  "question": "为什么一号线昨天订单达成率下降？",
  "scope": {"plant": "east_plant", "line": "line_01"}
}
```

## 身份边界

生产环境通过可信 Header 或短期 Subject Token 传递最终用户身份、Workspace 和对象范围。模型参数不能自行声明身份或扩大权限。
