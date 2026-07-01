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

- `10_Knowledge/**/*.md` 是否缺 frontmatter。
- 必填字段是否缺失。
- `status` 是否合法。
- `updated` 是否缺失或超过 180 天。
- `sku` / `aliases` 是否重复。
- `[[wikilink]]` 是否断链。
- 文档是否已经进入索引表。
