# LLM Wiki Frontmatter Schema

推荐每个正式知识页或 FAQ 页使用 YAML frontmatter。正文仍然给人读，frontmatter 给 RAG、健康检查和后续关系图使用。

## 通用知识页模板

```yaml
---
title: 企业知识库示例文档
type: knowledge_note
status: active
owner: nick
updated: 2026-06-29
customer_safe: false
rag: true
domain: default
category:
  - general
tags:
  - internal
summary: 这里写一句话摘要
sources:
  - type: manual
    ref: enterprise-wiki-manual
---
```

## 产品知识可选字段

产品、兼容性、方案类知识可以额外添加：

```yaml
---
product_line: optical
sku:
  - QSFP-100G-DR
  - QSFP-100G-FR
aliases:
  - FTLC4353RHPL
  - FTLC4353RJPL
applies_to:
  - 400G switch
  - 100G server
compatible_with:
  - QDD-400G-DR4
  - QDD-400G-XDR4
alternatives: []
limitations:
  - 需要确认客户设备品牌兼容
---
```

## 字段说明

- `title`: 页面标题，建议和一级标题一致。
- `type`: 页面类型。推荐 `knowledge_note`、`faq`、`policy`、`runbook`、`product_faq`、`product_spec`、`compatibility_note`、`solution_note`。
- `status`: `active`、`draft`、`archived`。
- `owner`: 维护人。
- `updated`: 最后确认日期，格式 `YYYY-MM-DD`。
- `domain`: 知识领域，例如 `default`、`product`、`it`、`hr`、`legal`。
  当前默认领域为 `default`，对应路径 `domains/default/**`。
- `category`: 页面分类。
- `tags`: 标签。
- `summary`: 一句话摘要。
- `customer_safe`: 是否可直接用于客户话术。第一版内部答案默认 `false`。
- `rag`: 是否进入 RAG 索引。正式知识默认 `true`。
- `sources`: 依据来源，人工维护也要写来源类型。
- `product_line`: 产品线，例如 `optical`。仅产品知识需要。
- `sku`: 标准型号列表。
- `aliases`: 别名、原厂型号、客户常用叫法。
- `applies_to`: 应用对象/场景。
- `compatible_with`: 兼容对象。
- `alternatives`: 替代料号。
- `limitations`: 限制条件。

## 健康检查规则

Admin Web 当前会检查：

- 启用领域的 `vault_subpath/10_Knowledge/**/*.md` 是否缺 frontmatter。
- 必填字段是否缺失。
- `domain` 是否缺失。
- `domain` 是否与领域注册表中的路径归属一致，例如 `domains/default/**` 应写 `domain: default`。
- `status` 是否合法。
- `updated` 是否缺失或超过 180 天。
- `sku` / `aliases` 是否重复。
- `[[wikilink]]` 是否断链。
- 文档是否已经进入索引表。

## 文档入库助手草稿规则

Admin Web 的“文档入库”只生成草稿，不直接生成正式知识。自动生成的 Markdown 必须默认：

```yaml
status: draft
rag: false
customer_safe: false
sources:
  - type: draft_import
    ref: 未提供正式来源
```

原始资料没有明确提供的技术事实必须保留为“待确认”，不能由模型自动补全。

## 多场景模板库

Admin Web 的“Schema 模板”页面提供以下可选模板：

| 模板 | 推荐 type | 使用范围 |
| --- | --- | --- |
| 通用知识 | `knowledge_note` | 稳定内部知识、说明和参考资料 |
| 产品知识 | `product_spec` | 型号、规格、兼容性、应用场景和替代方案 |
| 企业手册 | `policy` | 员工手册、企业制度、部门职责和内部政策 |
| 技术文档 | `knowledge_note` | 架构、接口、配置、版本约束和故障排查 |
| 流程 / SOP | `runbook` | 标准操作、审批、运维和应急处置流程 |

模板源文件位于 `docs/schema-templates/`。这些文件只是结构模板，不是正式知识，不会被 Vault 索引器读取。所有示例默认使用 `status: draft` 和 `rag: false`；管理员补充真实来源、替换占位符并人工确认后，才能将文档放入对应领域的 `10_Knowledge/` 目录并改为正式状态。
