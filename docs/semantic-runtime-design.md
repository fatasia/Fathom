# FATHOM 语义运行时 P0—P3 设计

## Requirements

### Functional

- 从发布的 MQL 和语义指标解析版本化物理映射；
- 在 PostgreSQL、SQLite/DuckDB 等事实源执行受控只读查询；
- 产生策略决定、物理计划、质量结果、血缘和执行收据；
- 把需求证据、黄金问题与语义/映射依赖关联；
- 以受治理能力目录向 MCP/Agent 开放查询和诊断；
- 支持多源选择、反向映射候选、需求探索和审批式洞察到动作。

### Non-Functional

- 安全：不接受模型生成 SQL；凭证只允许 `env://` 引用；默认只读；参数绑定；对象范围下推。
- 可靠：执行超时默认 8 秒，结果行数默认 1,000，上限 10,000；失败也生成收据。
- 可追溯：100% 运行关联语义、映射、策略、计划和来源版本。
- 可维护：连接器与语义内核解耦；第二数据源不得修改 MQL 语法。
- 兼容：现有内部观测执行作为无外部映射时的 fallback，现有 API 和 56 个基线测试保持兼容。

### Constraints

- 维持当前 Python/FastAPI/SQLAlchemy 单体部署，不为架构图拆微服务；
- 现阶段仅实现有限聚合与查询模式，不建设通用联邦 SQL 优化器；
- P3 动作仅实现审批、幂等和演示用受控状态变更，不提供任意写 SQL。

## Component Boundaries

| Component | Responsibility | Explicitly not responsible for |
|---|---|---|
| Mapping Registry | version, publish, rollback, schema compatibility | query execution |
| Physical Planner | compile closed MQL into connector-neutral plan | credentials, network I/O |
| Policy Enforcement Point | allow/deny and obligations | identity authentication |
| Connector Executor | safe read execution and limits | semantic inference |
| Runtime Orchestrator | coordinate and persist receipts | natural-language answer generation |
| Lineage & Quality | dependency/impact and runtime checks | workflow orchestration |
| Capability Registry | governed tool contracts | open-ended agent planning |
| Federation & Action | source routing and approved action dispatch | generic BPM/Saga engine |

## Failure Modes

| Failure | Behavior | Recovery |
|---|---|---|
| Mapping missing/unpublished | reject external execution, preserve internal fallback where allowed | publish a reviewed mapping |
| Schema drift | mark compatibility failed and block mapping publish/use | update mapping and rerun quality/golden gates |
| Source unavailable | select next eligible source or fail with receipt | repair source or change priority |
| Policy denied | no connector call; persist denied receipt | change role/scope through governance |
| Timeout/row limit | cancel/limit query and persist failure/partial receipt | narrow scope or adjust governed limit |
| Quality gate failed | return data with failed verification or block strict capability | repair source/mapping |
| Action duplicate | return existing idempotent result | inspect prior receipt |

## Delivery Mapping

- P0: mapping, planner, PEP, PostgreSQL executor, receipt, golden runtime cases.
- P1: requirement evidence, dependency edges, quality contracts, impact and release gates.
- P2: capability catalog and governed invocation; SQLite second-source adapter.
- P3: health/freshness source routing, reverse mapping candidates, requirement explorer, approved idempotent action.

