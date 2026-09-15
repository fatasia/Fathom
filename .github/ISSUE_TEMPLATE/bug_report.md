---
name: 缺陷报告
about: 报告可复现的缺陷，帮助我们定位问题
title: "[bug] "
labels: bug
assignees: ""
---

<!--
安全漏洞请勿使用本模板。请按 SECURITY.md 的渠道私下报告 security@example.com。
若问题涉及具体企业的数据或凭证，请先脱敏，不要粘贴真实凭证、连接串或客户数据。
-->

## 问题描述

<!-- 一句话说明发生了什么。 -->

## 环境

- 操作系统与版本（如 Windows 11 22621 / Ubuntu 24.04）：
- Python 版本（`python --version`）：
- Node.js 与 pnpm 版本（`node -v`、`pnpm -v`）：
- 安装方式：
  - [ ] `.\scripts\install.ps1 -LiteOnly`
  - [ ] `.\scripts\install.ps1`（含全部连接器）
  - [ ] 手动 `pip install -e '.[dev]'`
- FATHOM 版本（`apps/api/src/fathom/__init__.py` 中的 `__version__`）或提交哈希：
- 语义契约与版本（`semantic/` 下使用的文件及 `version` 字段）：
- 相关配置：是否设置了 `config/fathom.yaml`，涉及哪些数据源或模型网关（请只写类型，不要贴密钥）

## 复现步骤

1.
2.
3.

<!-- 越具体越好：页面路径、接口与请求体、CLI 子命令。 -->

最小复现请求或命令：

```
```

## 期望行为

<!-- 你预期发生什么。 -->

## 实际行为

<!-- 实际发生了什么。若是错误答案，请给出问题文本、语义版本与该问题在黄金问题集中的状态。 -->

## 日志与证据

<!-- 后端控制台输出、浏览器控制台报错、执行收据 ID（rcpt_ 开头）与策略决策 ID。 -->

```
```

## 补充信息

<!-- 已尝试的排查、是否可稳定复现（必现 / 偶发）、是否只在本机出现。 -->