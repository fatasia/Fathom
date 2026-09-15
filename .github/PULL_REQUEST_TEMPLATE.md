# 变更目的

<!-- 说明这次改动要解决什么问题、为什么这样改。若关联 issue，请写 Closes #123。 -->

## 变更类型

- [ ] `feat:` 新能力
- [ ] `fix:` 缺陷修复
- [ ] `docs:` 文档
- [ ] `chore:` 构建 / 依赖 / 打包

## 验证方式

<!-- 勾选已实际执行并通过的项。未执行或失败的项请如实说明，不要留空。 -->

- [ ] `python -m ruff check apps/api/src apps/api/tests` 通过
- [ ] `python -m pytest -q` 通过
- [ ] `pnpm --dir apps/web build` 通过

补充说明（手动验证步骤、截图、评测结果、未覆盖的部分）：

<!-- 例如：本地启动后按「治理 → 黄金问题集」跑通评测，阈值 0.99 通过；未做 PostgreSQL 实机验证。 -->

## 影响面

- 是否影响语义契约（`semantic/` 下的 YAML 资产、指标口径、维度、别名）？
  - [ ] 否
  - [ ] 是，已说明变更内容与兼容性：

- 是否影响发布包（`scripts/package-release.ps1` 的产物、打包内容、忽略规则）？
  - [ ] 否
  - [ ] 是，已说明产物差异：

- 是否涉及执行计划、策略执行点或执行收据的改动？
  - [ ] 否
  - [ ] 是，已说明影响的 ADR 与兼容性：

## 检查清单

- [ ] 提交信息使用 `feat:` / `fix:` / `docs:` / `chore:` 前缀，主题行能独立说明本次改动
- [ ] 未提交生成产物（`.venv/`、`apps/web/dist/`、`apps/web/node_modules/`、`data/*.db`、`artifacts/`、`dist/`）
- [ ] 未包含任何真实凭证、内网地址或客户名称
- [ ] 涉及架构级决策时已在 `docs/adr/` 补充 ADR