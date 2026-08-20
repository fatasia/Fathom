# 模型网关

模型不是 FATHOM 的事实源。模型负责意图翻译、候选语义生成、解释和跨模态理解；ONN
校验、权限、指标口径、确定性计算和证据链仍由 FATHOM 掌控。

## 双入口配置

- Web：系统设置 → 添加模型服务，适合业务管理员。
- YAML：`config/fathom.yaml`，适合 GitOps、离线部署和批量初始化。
- 环境变量：`FATHOM_*`，适合 CI/CD 与密钥注入。

优先级为环境变量、YAML、Web 持久化、默认值。页面展示配置来源；高优先级值不会被低优先级入口静默覆盖。

```yaml
model_gateway:
  providers:
    - key: primary_reasoner
      name: 主推理模型
      provider_type: openai_compatible
      base_url: https://model.example.com/v1
      api_mode: auto
      default_model: reasoning-model
      secret_reference: env://FATHOM_PRIMARY_MODEL_API_KEY
      enabled: true
      parameters:
        temperature: 0
        top_p: 0.9
        max_output_tokens: 2048
        timeout_seconds: 60
  routes:
    planner: primary_reasoner
    semantic_extractor: primary_reasoner
    explainer: primary_reasoner
```

## 自动发现与适配

一次“探测”包含两个不同门槛：

1. `/models`：获取模型目录，用户可以搜索选择或继续手工输入模型 ID。
2. 最小生成调用：分别测试 Responses 与 Chat Completions。能列出模型不等于有推理权限。

Messages、Embedding、Vision、Tool Calling 和 Structured Output 由供应商模板声明，发布前再由对应任务评测确认。所有供应商响应在内部归一化为文本、工具调用、用量和错误四类字段。

## 参数与任务路由

可调参数包括 `temperature`、`top_p`、`max_output_tokens`、超时、seed 与惩罚项，后端统一做边界校验。生产推荐：

- 规划与意图、语义抽取：`temperature=0`，强制结构化输出。
- 答案解释、Agent：低温度，并保持引用与 trace_id。
- Embedding：独立模型，不继承生成参数。
- Vision：独立角色，可按成本和数据合规路由到本地模型。

模型或参数发生变化时必须重新运行黄金问题、拒答、权限越权、SQL 安全和证据完整性评测，达到门槛后才能发布。

## 密钥

- Web 输入是 write-only，保存后立即清空。
- 本机使用操作系统凭证库，引用格式 `keyring://model/{provider}`。
- 服务器使用 `env://VARIABLE`，后续可接 Vault/KMS Secret Provider。
- API、日志、备份、YAML 和 SQLite 均不返回或保存明文 API Key。
