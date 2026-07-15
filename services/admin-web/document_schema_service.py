from __future__ import annotations

import json
import re
from datetime import date
from typing import Any

import yaml

from files_service import schema_template_by_id


def resolve_template(template_id: str) -> dict[str, str]:
    return schema_template_by_id(template_id)


def _template_markdown(content: str) -> str:
    match = re.search(r"```markdown\s*\n(.*?)\n```", content, re.DOTALL)
    if not match:
        raise ValueError("schema template does not contain a markdown block")
    return match.group(1).strip()


def _safe_name(title: str) -> str:
    return re.sub(r"[^A-Za-z0-9._\-\u4e00-\u9fff]+", "-", title).strip("-") or "draft"


def _replace_title_placeholder(body: str, title: str) -> str:
    return re.sub(r"^#\s+<[^>]+>", f"# {title}", body, count=1, flags=re.MULTILINE)


def enforce_template(markdown: str, template: dict[str, str], domain: str, owner: str) -> str:
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n?", markdown.strip(), re.DOTALL)
    if not match:
        return markdown.strip()
    try:
        frontmatter = yaml.safe_load(match.group(1)) or {}
    except Exception:
        return markdown.strip()
    if not isinstance(frontmatter, dict):
        return markdown.strip()
    frontmatter["type"] = template["type"]
    frontmatter["status"] = "draft"
    frontmatter["owner"] = owner
    frontmatter["updated"] = date.today().isoformat()
    frontmatter["domain"] = domain
    frontmatter["customer_safe"] = False
    frontmatter["rag"] = False
    body = markdown.strip()[match.end():].strip()
    serialized = yaml.safe_dump(frontmatter, allow_unicode=True, sort_keys=False).strip()
    return f"---\n{serialized}\n---\n\n{body}\n"


def system_prompt(template: dict[str, str]) -> str:
    return f"""/no_think
你是企业知识库的文档标准化入库助手。不要输出思考过程。

目标：把用户提供的粗糙 Markdown 或文本资料整理成“{template["label"]}”Schema 草稿。

硬规则：
1. 只生成草稿，不生成正式知识。
2. frontmatter 必须设置 type: {template["type"]}、status: draft、rag: false、customer_safe: false。
3. 严格沿用下方选定模板的字段和正文结构，不得切换到产品文档或其他模板。
4. 不自动补全原文没有的事实；缺失内容写“待确认：原始文档未提供明确依据”。
5. 不编造制度条款、技术参数、操作步骤、兼容性、限制条件、替代方案或来源。
6. 只保留与“{template["description"]}”相关的有效内容；页眉页脚、页码、广告、版权声明和无关介绍应清洗。
7. 如果原文信息不足，要在 review_report 中列出缺口和建议确认问题。
8. 输出必须是严格 JSON，不要 Markdown fenced code，不要解释文字。

选定 Schema 模板：
{template["content"]}

JSON 格式：
{{
  "rewritten_markdown": "完整 Markdown 草稿",
  "review_report": {{
    "missing_fields": [],
    "uncertain_claims": [],
    "suggested_questions": [],
    "removed_irrelevant_content": [],
    "suggested_path": "domains/<domain>/20_Drafts/<filename>.md",
    "ready_for_active": false,
    "notes": []
  }}
}}
"""


def user_prompt(
    raw_markdown: str,
    domain: str,
    template: dict[str, str],
    owner: str,
    removed_items: list[str],
) -> str:
    return f"""请按已选 Schema 标准化以下原始文档。

上下文：
- domain: {domain}
- schema_id: {template["id"]}
- schema_label: {template["label"]}
- required type: {template["type"]}
- owner: {owner}
- updated: {date.today().isoformat()}
- 输出必须保持 draft：status=draft, rag=false, customer_safe=false
- 如果原文不足，不要补事实，使用“待确认：原始文档未提供明确依据”
- 输入文本已经过预清洗，不要恢复被移除的噪声内容
- review_report.removed_irrelevant_content 需要概括列出被清洗或忽略的无关内容

预清洗移除项：
{json.dumps(removed_items[:30], ensure_ascii=False, indent=2)}

原始 Markdown：
---
{raw_markdown.strip()}
---
"""


def fallback_draft(
    raw_markdown: str,
    domain: str,
    template: dict[str, str],
    owner: str,
    reason: str,
    removed_items: list[str],
) -> tuple[str, dict[str, Any]]:
    template_markdown = _template_markdown(template["content"])
    title = next(
        (
            line.lstrip("#").strip()[:80]
            for line in raw_markdown.splitlines()
            if line.strip().startswith("#") and line.lstrip("#").strip()
        ),
        "待整理文档",
    )
    frontmatter_match = re.match(r"^---\s*\n(.*?)\n---\s*\n?", template_markdown, re.DOTALL)
    if not frontmatter_match:
        raise ValueError("schema template frontmatter is invalid")
    frontmatter = yaml.safe_load(frontmatter_match.group(1)) or {}
    frontmatter.update(
        {
            "title": title,
            "type": template["type"],
            "status": "draft",
            "owner": owner,
            "updated": date.today().isoformat(),
            "domain": domain,
            "customer_safe": False,
            "rag": False,
        }
    )
    body = _replace_title_placeholder(template_markdown[frontmatter_match.end():].strip(), title)
    excerpt = raw_markdown.strip()[:4000]
    serialized = yaml.safe_dump(frontmatter, allow_unicode=True, sort_keys=False).strip()
    markdown = (
        f"---\n{serialized}\n---\n\n{body}\n\n"
        "## 清洗后资料摘录\n\n"
        "以下内容仅供人工整理，不代表已确认知识。\n\n"
        f"```text\n{excerpt}\n```\n"
    )
    report = {
        "missing_fields": ["sources", "summary", "模板扩展字段"],
        "uncertain_claims": ["模型重写失败，已生成所选 Schema 的保守草稿，正文事实需人工确认。"],
        "suggested_questions": [
            "文档的正式名称、适用范围和责任人是什么？",
            "原始材料中的哪些内容已完成事实确认？",
            "是否有正式来源、版本或审批记录可以引用？",
        ],
        "removed_irrelevant_content": removed_items,
        "suggested_path": f"domains/{domain}/20_Drafts/{_safe_name(title)}.md",
        "ready_for_active": False,
        "notes": [reason, f"已按 {template['label']} 模板生成回退草稿。"],
    }
    return markdown, report
