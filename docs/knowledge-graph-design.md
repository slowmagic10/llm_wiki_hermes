# 知识图谱可视化设计

## 1. 定位

本项目的知识图谱用于 Admin Web 中展示正式 Wiki 的可解释关系，帮助管理员检查文档结构、产品/SKU 关系和双链连接情况。

它不是独立的大型图数据库系统，也不替代 RAG 主链路。RAG 仍负责问答检索，知识图谱负责可视化和治理观察。

## 2. 设计原则

1. 只展示显式关系，不展示模型推断关系。
2. 图谱不写回 Markdown，不自动修改 Vault。
3. 知识缺口、维护建议、问答审计不进入图谱，分别放在独立页面。
4. 向量相似度不作为图谱主干关系，避免把“语义相近”误展示成“知识上有关联”。
5. 图谱数据从当前数据库和 Markdown metadata 在线生成，不维护第二套离线产物。

## 3. 数据来源

强关系来源只允许以下几类：

| 来源 | 用途 |
| --- | --- |
| Markdown 路径 | domain、folder、document 层级 |
| frontmatter | SKU、别名、兼容、替代、限制、适用场景、标签、文档类型 |
| Obsidian 双链 | 文档到文档的 `LINKS_TO` |
| 索引元数据 | chunks 数、状态、已索引文档集合 |

暂不使用 LLM 自动抽取边。后续如果引入，也只能进入候选关系审核流程，不能直接进入正式图谱。

## 4. 图谱模型

`/api/knowledge-map` 返回正式图谱字段：

```json
{
  "schema": {
    "version": "2026-07-kg-v1",
    "relation_types": {}
  },
  "summary": {
    "nodes": 100,
    "edges": 200
  },
  "nodes": [
    {
      "id": "SKU:qsfp-100g-dr",
      "type": "SKU",
      "label": "QSFP-100G-DR",
      "metadata": {}
    }
  ],
  "edges": [
    {
      "source": "Document:domains/default/10_knowledge/products/qsfp-100g-dr-fr.md",
      "target": "SKU:qsfp-100g-dr",
      "type": "MENTIONS_SKU",
      "level": "strong",
      "method": "frontmatter",
      "source_path": "domains/default/10_Knowledge/Products/QSFP-100G-DR-FR.md"
    }
  ]
}
```

接口仍保留 `domains`、`folders`、`documents`、`products`、`tags` 等兼容字段，用于现有页面列表和详情面板。

## 5. 节点类型

| 类型 | 含义 |
| --- | --- |
| `Domain` | 知识库领域 |
| `Folder` | Vault 内目录 |
| `Document` | Markdown 文档 |
| `Tag` | 文档标签 |
| `DocType` | 文档类型 |
| `Category` | 业务分类 |
| `ProductLine` | 产品线 |
| `SKU` | 产品型号、线缆、模块或其他可销售对象 |
| `Alias` | SKU 别名 |
| `Limitation` | 限制条件 |
| `Scenario` | 适用场景、使用对象或方案 |

## 6. 关系白名单

| 关系 | 含义 |
| --- | --- |
| `Document --IN_DOMAIN--> Domain` | 文档所属领域 |
| `Document --IN_FOLDER--> Folder` | 文档所在目录 |
| `Folder --FOLDER_IN_DOMAIN--> Domain` | 目录所属领域 |
| `Document --HAS_TAG--> Tag` | 文档标签 |
| `Document --HAS_TYPE--> DocType` | 文档类型 |
| `Document --IN_CATEGORY--> Category` | 文档分类 |
| `Document --ABOUT_PRODUCT_LINE--> ProductLine` | 文档关联产品线 |
| `Document --MENTIONS_SKU--> SKU` | 文档声明某个 SKU |
| `SKU --HAS_ALIAS--> Alias` | SKU 别名 |
| `SKU --COMPATIBLE_WITH--> SKU` | SKU 兼容对象 |
| `SKU --ALTERNATIVE_TO--> SKU` | SKU 替代对象 |
| `SKU --HAS_LIMITATION--> Limitation` | SKU 限制条件 |
| `SKU --APPLIES_TO--> Scenario` | SKU 适用场景 |
| `Document --LINKS_TO--> Document` | Obsidian 双链 |

## 7. 前端展示

Admin Web 当前保留两个视图：

1. 产品关系图：展示 `SKU` 与 `Document` 的关系，点击 SKU 后展示 aliases、兼容对象、替代方案、限制条件和文档来源。
2. 结构图：展示 `Domain -> Folder -> Document` 的结构关系。

后续如果要增加高级视图，应基于同一份 `nodes/edges` 数据过滤展示，而不是另起一套关系生成逻辑。

## 8. 非目标

以下内容当前不进入知识图谱：

1. 知识缺口。
2. 维护建议。
3. 问答审计日志。
4. 向量相似度边。
5. LLM 自动抽取但未经人工确认的关系。

这些内容可以继续留在 Admin Web 的独立栏目里，用于治理和排查，但不应污染正式知识关系图。
