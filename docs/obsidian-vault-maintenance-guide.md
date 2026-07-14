# Obsidian Vault 知识维护手册

更新时间：2026-07-14

本文档说明如何维护 LLM Wiki 的正式 Markdown 知识、通过 Git 同步到服务器，以及如何确认 RAG 索引已经更新。

## 1. 维护原则

1. Obsidian Vault 是正式知识的唯一事实来源。
2. Vault 只保存稳定、已确认、可长期复用的知识。
3. 聊天记录、临时讨论、知识缺口和运行日志不写入 Vault。
4. 正式 Markdown 只能由管理员人工确认后修改。
5. Hermes、RAG 服务和 obsidian-wiki 不自动改写正式 Markdown。
6. 本地 Obsidian 打开的 Git 仓库是日常编辑入口；服务器 Vault 是部署副本。
7. 文档变更后必须重新同步索引，只有 Git 更新并不等于 RAG 已更新。

## 2. 当前数据流

```text
本地 Obsidian Vault
  -> git commit / git push
  -> 远端 Git 仓库
  -> 服务器 /root/llm_wiki_hermes/vault
  -> llm-wiki-sync-runner 每日 git pull
  -> RAG 增量同步
  -> Postgres 元数据与 FTS + Milvus 向量
```

当前服务器路径：

```text
/root/llm_wiki_hermes/vault
```

领域目录结构：

```text
vault/
  domains/
    default/
      00_Templates/
      10_Knowledge/
      90_Archive/
```

新增领域时使用：

```text
vault/domains/<domain>/
  00_Templates/
  10_Knowledge/
  90_Archive/
```

## 3. 目录使用规则

### 3.1 00_Templates

保存该领域的 Markdown 模板，不作为正式答案依据。

模板可以设置：

```yaml
status: draft
rag: false
domain: default
```

### 3.2 10_Knowledge

保存正式、当前有效的知识。

只有人工确认后，文档才能设置：

```yaml
status: active
rag: true
```

### 3.3 90_Archive

保存仍有历史价值但不应继续参与问答的文档。

建议设置：

```yaml
status: archived
rag: false
```

如果内容已经完全错误且没有保留价值，可以直接删除；下一次同步会删除对应索引。

## 4. Frontmatter 要求

完整规范参见：

```text
/root/llm_wiki_hermes/docs/wiki-frontmatter-schema.md
```

正式知识页至少维护：

```yaml
---
title: 文档标题
type: knowledge_note
status: active
owner: nick
updated: 2026-07-14
customer_safe: false
rag: true
domain: default
category:
  - general
tags:
  - internal
summary: 一句话说明文档内容
sources:
  - type: manual
    ref: 内部确认记录或资料名称
---
```

关键要求：

1. `domain` 必须与目录所属领域一致。
2. `updated` 是最后一次人工确认日期，不是自动生成日期。
3. `sources` 记录事实依据；没有依据的内容不能升级为正式知识。
4. `rag: true` 只用于允许进入正式问答的内容。
5. 产品型号、别名、兼容对象、替代料号和限制条件应优先写入结构化字段。
6. 未确认内容使用 `status: draft` 和 `rag: false`。

## 5. 正文建议结构

产品或方案类知识建议使用：

```markdown
# 标题

## 一句话结论

## 型号对应

## 适用场景

## 兼容性

## 限制条件

## 售前确认点

## 替代方案

## 相关知识
```

规则：

1. 结论写明确事实，不写推测。
2. 兼容性必须带条件、版本或设备范围。
3. 无法确认的字段写“待确认”，不要让模型补全。
4. 同一事实尽量只维护在一个主页面，其他页面使用 `[[wikilink]]` 引用。
5. 不为知识图谱目的制造无意义双链。

## 6. 新增文档流程

### 6.1 编辑前同步本地仓库

在本地 Vault 仓库执行：

```bash
git pull --ff-only
```

如果有未提交修改，先检查并处理，避免把不同批次的知识混在同一个提交中。

### 6.2 创建 Markdown

1. 确认所属领域。
2. 在 `domains/<domain>/10_Knowledge` 下选择合适目录。
3. 从 `00_Templates` 复制模板，或使用 Admin Web 的“文档入库”生成草稿。
4. 补全 frontmatter。
5. 删除与正式知识无关的宣传、版权、目录、页眉页脚和重复内容。
6. 人工核对型号、参数、限制条件和来源。
7. 将确认后的草稿改为 `status: active`、`rag: true`。

### 6.3 提交变更

```bash
git status
git diff
git add path/to/document.md
git commit -m "docs: update wiki knowledge"
git push
```

不要提交：

1. Obsidian 临时缓存。
2. PDF 原文件，除非知识仓库明确决定保留。
3. 运行日志、数据库、embedding 或备份包。
4. 未经确认的模型输出。

## 7. 修改、重命名和删除

### 7.1 修改

1. 修改正文和结构化字段。
2. 更新 `updated`。
3. 如果事实依据变化，同时更新 `sources`。
4. 检查引用该页面的双链是否仍然成立。

### 7.2 重命名或移动

优先在 Obsidian 内完成重命名，让 Obsidian 更新双链。

提交前检查：

```bash
git status
git diff --check
```

服务器同步后，旧路径索引会被删除，新路径会重新索引。

### 7.3 删除过期知识

完全错误且无历史价值：

```bash
git rm path/to/obsolete-document.md
git commit -m "docs: remove obsolete wiki knowledge"
git push
```

仍需保留历史：

1. 移到 `90_Archive`。
2. 设置 `status: archived`。
3. 设置 `rag: false`。
4. 提交并推送。

不需要在数据库中手工删除；同步器会处理删除或移出索引范围的文档。

## 8. PDF 和粗糙资料入库

推荐使用 Admin Web：

```text
http://192.168.121.20:18090
文档入库
```

流程：

```text
上传 PDF / 粘贴 Markdown
  -> 提取文本
  -> 模型生成标准化草稿
  -> 自动标记 draft + rag:false
  -> 管理员删除无关内容并核对事实
  -> 保存到本地 Vault
  -> 改为 active + rag:true
  -> Git 提交
```

注意：

1. PDF 文本提取不等于事实审核。
2. 产品无关的公司介绍、免责声明、版权页、重复表格和营销语言应删除。
3. 图片中的信息当前不作为主要解析目标。
4. 模型不能根据常识补齐资料中不存在的参数。

## 9. 让更新生效

### 9.1 每日自动同步

`llm-wiki-sync-runner` 每 86400 秒执行一次：

```text
git pull --ff-only
  -> POST /admin/sync/run
```

### 9.2 Admin 立即同步

在 Admin Web 的“同步管理”点击：

```text
Git Pull + 重新索引
```

### 9.3 服务器命令行立即同步

```bash
cd /root/llm_wiki_hermes/vault
git pull --ff-only

curl --noproxy "*" -X POST   http://127.0.0.1:18080/admin/sync/run
```

查看结果：

```bash
cat /root/llm_wiki_hermes/logs/llm-wiki-sync-status.json
docker logs --tail 120 llm-wiki-sync-runner
```

## 10. 更新后验证

在 Admin Web 依次检查：

1. “同步管理”：最近同步为 success。
2. “健康检查”：Wiki 质量没有 error。
3. “文档浏览”：能看到新路径和 frontmatter。
4. “领域管理”：文档路径属于正确领域。
5. “RAG 测试”：使用文档中的明确事实提问，确认来源路径正确。

命令行检查：

```bash
curl --noproxy "*" http://127.0.0.1:18090/api/wiki-health
curl --noproxy "*" http://127.0.0.1:18090/api/health-detail
```

## 11. obsidian-wiki 的作用

`ar9av/obsidian-wiki` 是离线维护辅助工具，不是实时 RAG。

当前可用于：

1. 检查 Vault 配置。
2. 辅助发现断链、孤立页和标签问题。
3. 提供 cross-link 或整理建议。
4. 辅助把原始资料整理成 Markdown 草稿。

检查安装状态：

```bash
docker exec llm-wiki-admin-web obsidian-wiki info
```

边界：

1. 不直接参与 `/wiki` 问答。
2. 不代替 embedding、Milvus 或 reranker。
3. 不自动修改正式知识。
4. 所有写入建议必须经过管理员审核和 Git 提交。

## 12. 多领域维护

新增领域时需要同时完成：

1. 在 Admin Web“领域管理”新增领域并保存。
2. 在 Vault 创建 `domains/<domain>/00_Templates`、`10_Knowledge`、`90_Archive`。
3. 新文档 frontmatter 使用对应 `domain`。
4. 在 Admin 点击“应用入口配置”。
5. 页面提示需要重启时，在服务器执行 `docker restart hermes`。
6. 重新索引并验证领域入口。

不同启用领域的 Vault 子目录不能相同或互相嵌套。

## 13. 常见问题

### 13.1 Git push 认证失败

GitHub HTTPS 不支持账户密码。使用 SSH key 或 Personal Access Token。

SSH 验证：

```bash
ssh -T git@github.com
```

### 13.2 服务器 git pull 无法解析 github.com

这是服务器 DNS 或网络问题，不是 Vault 或 RAG 问题。

检查：

```bash
getent hosts github.com
ssh -T git@github.com
```

网络恢复后，在 Admin 重新执行“Git Pull + 重新索引”。

### 13.3 Git 已更新但问答仍是旧内容

原因通常是只执行了 `git pull`，没有执行 RAG 同步。

处理：

```bash
curl --noproxy "*" -X POST   http://127.0.0.1:18080/admin/sync/run
```

### 13.4 文档没有进入索引

检查：

1. 是否位于启用领域的 `10_Knowledge` 下。
2. `rag` 是否为 `true`。
3. `status` 是否为 `active`。
4. `domain` 是否与路径一致。
5. Admin“健康检查”是否报告 frontmatter 错误。
6. 最近同步日志是否包含该文件错误。

## 14. 发布检查清单

- [ ] 内容是稳定知识，不是聊天记录或临时讨论。
- [ ] frontmatter 完整且 `domain` 正确。
- [ ] 参数、型号和限制条件已人工确认。
- [ ] 无关宣传和重复内容已经删除。
- [ ] `updated` 与 `sources` 已更新。
- [ ] Git diff 只包含本次知识变更。
- [ ] 已 push 到远端仓库。
- [ ] 已完成 RAG 同步。
- [ ] Admin 健康检查无错误。
- [ ] RAG 测试来源路径正确。
