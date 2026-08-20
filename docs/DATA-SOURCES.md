# 数据源与连接器策略

FATHOM 覆盖企业常见的 SQL、半结构 KV、图、时序、向量和文本数据源，并提供制造业协议入口。

| 类别 | 首批连接器 | 部署策略 |
|---|---|---|
| SQL | SQLite、DuckDB、PostgreSQL、MySQL、SQL Server、Oracle | SQLite/DuckDB 内置，其余驱动按需安装 |
| KV | Redis、REST KV | 插件 |
| 图 | Neo4j、Apache AGE/RDF 适配口 | 插件，Lite 默认仍使用关系边表 |
| 时序 | TDengine、Historian、Timescale/SQL 时序 | TDengine 优先 WebSocket，REST 用于兼容性查询 |
| 向量 | sqlite-vec、pgvector、Qdrant | sqlite-vec 内置但默认关闭，专用服务按需启用 |
| 文本 | 文件、Elasticsearch、对象存储适配口 | 文件内置，其余插件 |
| 工业协议 | OPC UA、MQTT、CDC | 插件；写入和控制能力默认关闭 |

连接器统一实现：配置校验、连接测试、Schema/元数据发现、采样、增量游标、类型转换、ONN Scaffold、查询下推、权限和审计。凭证只保存 `env://` 或 Secret Provider 引用，不进入普通配置和前端日志。
