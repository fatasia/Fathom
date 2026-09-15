# Changelog

本文件记录 FATHOM 的显著变更。格式遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循[语义化版本](https://semver.org/lang/zh-CN/)。

## [Unreleased]

### Added

- 新增 MIT 协议，版权行署名 `Copyright (c) 2026 FATHOM contributors`。
- 新增开源治理文件：`CONTRIBUTING.md`、`SECURITY.md`、`CODE_OF_CONDUCT.md`、
  `.github/PULL_REQUEST_TEMPLATE.md` 与 `.github/ISSUE_TEMPLATE/` 下的缺陷与功能建议模板。
- 新增本 CHANGELOG，作为对外披露变更与安全修复的统一入口。
- 黄金问题集与示例数据集改为 `seed/golden-questions.yaml` 与 `seed/demo-dataset.yaml`，
  与语义契约 `semantic/manufacturing.execution.yaml` 配套，clone 后即可直接初始化并运行评测。
- 示例数据集使用相对日期偏移，任何时间 clone 都能直接演示可信问数、语义运行时与黄金问题评测。

### Changed

- 凭证处理统一为环境变量或 `secret_reference` 引用，配置样例与文档只保留引用形式，
  不再出现任何真实密钥。
- 文档去除内部缩写与内部代号，统一使用公开发布口径的业务术语。
- 语义契约、策略执行点与执行收据的设计依据整理为 `docs/adr/` 下的公开 ADR，
  并在贡献指南中说明新增契约的检查清单。

### Fixed

- 移除全部厂商专有信息与企业内部代号，仓库内只保留通用业务术语与开放接口契约
  （REST/OpenAPI、SSE、MCP、A2A，以及 Dify 工具与 Chatflow）。
- 移除对内部联调痕迹的依赖，测试夹具改为仓库内自包含的示例数据。
- 修正发布打包的编码处理，避免非 ASCII 文件名（如三份中文文档）在压缩包中被静默丢弃。
- 修正 SPA 兜底路由，使未知 `/api/*` 路径返回 404 而非 200 HTML。