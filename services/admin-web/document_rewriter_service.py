from __future__ import annotations

import json
import re
from datetime import date
from typing import Any

import httpx
import yaml
from fastapi import HTTPException

from config import LITELLM_BASE_URL
from document_schema_service import (
    enforce_template,
    fallback_draft,
    resolve_template,
    system_prompt as schema_system_prompt,
    user_prompt as schema_user_prompt,
)
from model_settings import effective_model_settings, litellm_headers
from utils import jsonable


REQUIRED_FRONTMATTER = ("title", "type", "status", "owner", "updated", "domain", "rag", "customer_safe")

NOISE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("pdf_page_header_footer", re.compile(r"数据表\s*[|｜]\s*\d+\s*$")),
    ("standalone_page_marker", re.compile(r"^##\s*第\s*\d+\s*页\s*$")),
    ("call_to_action", re.compile(r"准备好开始了吗|如需了解更多|请访问", re.IGNORECASE)),
    ("source_url", re.compile(r"https?://|www\.|nvidia\.cn/products|/professional-desktop-gpus/", re.IGNORECASE)),
    ("copyright_trademark_legal", re.compile(r"©|保留所有权利|商标|注册商标|copyright|trademark|all rights reserved", re.IGNORECASE)),
    ("khronos_conformance_note", re.compile(r"khronos|conformance|一致性状态|构象测试|符合性测试", re.IGNORECASE)),
    ("pdf_footnote", re.compile(r"^\s*\d+\.\s*(峰值速率|采用稀疏|产品基于已发布)")),
    ("document_tracking_code", re.compile(r"\b\d{6,}\b.*\d{4}\s*年\s*\d{1,2}\s*月")),
)

UNIVERSAL_NOISE_REASONS = {
    "pdf_page_header_footer",
    "standalone_page_marker",
    "call_to_action",
    "document_tracking_code",
}

def _extract_json(text: str) -> dict[str, Any]:
    candidate = text.strip()
    if candidate.startswith("```"):
        candidate = re.sub(r"^```(?:json)?\s*", "", candidate)
        candidate = re.sub(r"\s*```$", "", candidate)
    try:
        payload = json.loads(candidate)
    except Exception:
        match = re.search(r"\{.*\}", candidate, re.DOTALL)
        if not match:
            raise HTTPException(status_code=502, detail="model did not return JSON")
        try:
            payload = json.loads(match.group(0))
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"model JSON parse failed: {exc}") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=502, detail="model JSON must be an object")
    return payload


def _parse_frontmatter(markdown: str) -> tuple[dict[str, Any], str]:
    if not markdown.startswith("---"):
        return {}, markdown
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n?", markdown, re.DOTALL)
    if not match:
        return {}, markdown
    try:
        data = yaml.safe_load(match.group(1)) or {}
    except Exception:
        data = {}
    return data if isinstance(data, dict) else {}, markdown[match.end():]


def _validate_markdown(markdown: str) -> dict[str, Any]:
    frontmatter, body = _parse_frontmatter(markdown)
    missing = [key for key in REQUIRED_FRONTMATTER if key not in frontmatter or frontmatter.get(key) in ("", None)]
    warnings: list[str] = []
    errors: list[str] = []
    if not frontmatter:
        errors.append("missing_frontmatter")
    if str(frontmatter.get("status") or "").lower() != "draft":
        errors.append("status_must_be_draft")
    if frontmatter.get("rag") is not False:
        errors.append("rag_must_be_false_for_generated_draft")
    if frontmatter.get("customer_safe") is not False:
        warnings.append("customer_safe_should_be_false_by_default")
    if len(body.strip()) < 80:
        warnings.append("body_too_short")
    for field in ("sources", "summary"):
        if field not in frontmatter:
            warnings.append(f"missing_recommended_field:{field}")
    return {
        "ok": not errors and not missing,
        "missing_required_fields": missing,
        "errors": errors,
        "warnings": warnings,
        "frontmatter": frontmatter,
    }


def _clean_source_markdown(raw_markdown: str, template_id: str = "product") -> tuple[str, list[str]]:
    removed: list[str] = []
    cleaned_lines: list[str] = []
    previous_blank = False
    lines = raw_markdown.replace("\r\n", "\n").splitlines()
    start_index = 0

    if lines and lines[0].strip() == "---":
        for index, raw_line in enumerate(lines[1:], start=1):
            if raw_line.strip() == "---":
                for frontmatter_line in lines[: index + 1]:
                    removed.append(f"去除导入草稿 frontmatter：{frontmatter_line.strip()[:80] or '<blank>'}")
                start_index = index + 1
                break

    for raw_line in lines[start_index:]:
        line = raw_line.strip()

        if line.startswith("> 来源 PDF："):
            removed.append(f"去除导入来源提示：{line[:80]}")
            continue
        if re.match(r"^#\s+workstation-datasheet-|^#\s+.*\.pdf$", line, re.IGNORECASE):
            removed.append(f"去除文件名标题：{line[:80]}")
            continue

        matched_reason = None
        for reason, pattern in NOISE_PATTERNS:
            if template_id != "product" and reason not in UNIVERSAL_NOISE_REASONS:
                continue
            if pattern.search(line):
                matched_reason = reason
                break
        if matched_reason:
            removed.append(f"{matched_reason}: {line[:120]}")
            continue

        if not line:
            if previous_blank:
                continue
            previous_blank = True
            cleaned_lines.append("")
            continue

        previous_blank = False
        cleaned_lines.append(raw_line.rstrip())

    cleaned = "\n".join(cleaned_lines).strip()
    if not cleaned:
        cleaned = raw_markdown.strip()
        removed.append("清洗结果为空，已回退使用原文")
    return cleaned, removed[:80]


def _system_prompt() -> str:
    return """/no_think
你是企业知识库的文档标准化入库助手。不要输出思考过程。

目标：把用户提供的粗糙 Markdown 或产品说明整理成标准 Wiki 草稿。

硬规则：
1. 只生成草稿，不生成正式知识。
2. frontmatter 必须设置 status: draft、rag: false、customer_safe: false。
3. 不自动补全原文没有的技术事实；缺失内容写“待确认：原始文档未提供明确依据”。
4. 不编造兼容性、限制条件、替代方案、客户话术或来源。
5. 如果原文信息不足，要在 review_report 中列出缺口和建议确认问题。
6. 输出必须是严格 JSON，不要 Markdown fenced code，不要解释文字。

标准 Markdown 结构：
---
title: ...
type: product_note
status: draft
owner: ...
updated: YYYY-MM-DD
customer_safe: false
rag: false
domain: ...
category:
  - product
tags:
  - draft
summary: ...
product_line: ...
sku: []
aliases: []
applies_to: []
compatible_with: []
alternatives: []
limitations: []
sources:
  - type: draft_import
    ref: 未提供正式来源
---

# 标题

## 一句话结论

## 适用场景

## 兼容性

## 限制条件

## 可替代方案

## 售前问答

## 来源

JSON 格式：
{
  "rewritten_markdown": "完整 Markdown 草稿",
  "review_report": {
    "missing_fields": [],
    "uncertain_claims": [],
    "suggested_questions": [],
    "removed_irrelevant_content": [],
    "suggested_path": "domains/<domain>/20_Drafts/<filename>.md",
    "ready_for_active": false,
    "notes": []
  }
}
"""


def _guess_title(raw_markdown: str) -> str:
    for line in raw_markdown.splitlines():
        text = line.strip()
        if text.startswith("#"):
            return text.lstrip("#").strip()[:80] or "待整理产品文档"
    for line in raw_markdown.splitlines():
        text = line.strip()
        if text:
            return text[:80]
    return "待整理产品文档"


def _yaml_scalar(value: Any) -> str:
    return json.dumps(str(value), ensure_ascii=False)


def _fallback_result(
    raw_markdown: str,
    domain: str,
    doc_type: str,
    owner: str,
    reason: str,
    removed_items: list[str] | None = None,
) -> dict[str, Any]:
    today = date.today().isoformat()
    title = _guess_title(raw_markdown)
    safe_name = re.sub(r"[^A-Za-z0-9._\-\u4e00-\u9fff]+", "-", title).strip("-") or "draft"
    excerpt = raw_markdown.strip()[:4000]
    markdown = f"""---
title: {_yaml_scalar(title)}
type: {_yaml_scalar(doc_type)}
status: draft
owner: {_yaml_scalar(owner)}
updated: {_yaml_scalar(today)}
customer_safe: false
rag: false
domain: {_yaml_scalar(domain)}
category:
  - product
tags:
  - draft
summary: {_yaml_scalar("待确认：原始文档未提供足够信息，需要人工整理确认。")}
product_line: {_yaml_scalar("待确认")}
sku: []
aliases: []
applies_to: []
compatible_with: []
alternatives: []
limitations: []
sources:
  - type: draft_import
    ref: 未提供正式来源
---

# {title}

## 一句话结论

待确认：原始文档未提供明确依据。

## 适用场景

- 待确认：原始文档未提供明确依据。

## 兼容性

- 待确认：原始文档未提供明确依据。

## 限制条件

- 待确认：原始文档未提供明确依据。

## 可替代方案

- 待确认：原始文档未提供明确依据。

## 售前问答

### Q: 这个文档中的产品适合什么场景？

A: 待确认：原始文档未提供明确依据。

## 清洗后资料摘录

```text
{excerpt}
```

## 来源

- draft_import：未提供正式来源。
"""
    report = {
        "missing_fields": ["sku", "applies_to", "compatible_with", "alternatives", "limitations", "sources"],
        "uncertain_claims": ["模型重写失败，已生成保守模板草稿。所有技术结论均需要人工确认。"],
        "suggested_questions": [
            "该产品的标准型号和别名是什么？",
            "该产品适用于哪些明确场景？",
            "有哪些兼容对象、限制条件和替代方案？",
            "是否有正式来源或厂家资料可以引用？",
        ],
        "removed_irrelevant_content": removed_items or [],
        "suggested_path": f"domains/{domain}/20_Drafts/{safe_name}.md",
        "ready_for_active": False,
        "notes": [reason, f"已在重写前清洗 {len(removed_items or [])} 条明显非产品知识内容。"],
    }
    validation = _validate_markdown(markdown)
    return jsonable(
        {
            "rewritten_markdown": markdown,
            "review_report": report,
            "validation": validation,
            "model": "fallback-template",
            "usage": {},
            "notes": {
                "write_policy": "preview_only_no_vault_write",
                "fallback": True,
                "fallback_reason": reason,
                "next_step": "人工确认后再保存到 20_Drafts；转正式前手动改 status=active, rag=true。",
            },
        }
    )


def _schema_fallback_result(
    raw_markdown: str,
    domain: str,
    template: dict[str, str],
    owner: str,
    reason: str,
    removed_items: list[str],
) -> dict[str, Any]:
    markdown, report = fallback_draft(
        raw_markdown=raw_markdown,
        domain=domain,
        template=template,
        owner=owner,
        reason=reason,
        removed_items=removed_items,
    )
    return jsonable(
        {
            "rewritten_markdown": markdown,
            "review_report": report,
            "validation": _validate_markdown(markdown),
            "model": "fallback-template",
            "usage": {},
            "selected_schema": {
                "id": template["id"],
                "label": template["label"],
                "type": template["type"],
            },
            "notes": {
                "write_policy": "preview_only_no_vault_write",
                "fallback": True,
                "fallback_reason": reason,
                "next_step": "人工确认后再保存到 20_Drafts；转正式前手动改 status=active, rag=true。",
            },
        }
    )


def _user_prompt(
    raw_markdown: str,
    domain: str,
    profile: str,
    doc_type: str,
    owner: str,
    removed_items: list[str],
) -> str:
    today = date.today().isoformat()
    return f"""请标准化以下原始文档。

上下文：
- domain: {domain}
- profile: {profile}
- preferred type: {doc_type}
- owner: {owner}
- updated: {today}
- 输出必须保持 draft：status=draft, rag=false, customer_safe=false
- 如果原文不足，不要补事实，使用“待确认：原始文档未提供明确依据”
- 输入文本已经过预清洗。不要把页眉页脚、页码、CTA、URL、版权商标声明、法律声明、脚注、一致性测试说明写入正式草稿正文。
- 只保留产品定义、规格参数、特性、适用场景、限制、兼容/接口/功耗/外形/API 信息。
- review_report.removed_irrelevant_content 需要概括列出被清洗或被忽略的非产品内容。

预清洗移除项：
{json.dumps(removed_items[:30], ensure_ascii=False, indent=2)}

原始 Markdown：
---
{raw_markdown.strip()}
---
"""


async def rewrite_document(raw_markdown: str, domain: str, template_id: str, owner: str) -> dict[str, Any]:
    raw_markdown = raw_markdown.strip()
    if len(raw_markdown) < 20:
        raise HTTPException(status_code=400, detail="raw_markdown is too short")
    if len(raw_markdown) > 60000:
        raise HTTPException(status_code=400, detail="raw_markdown is too long")
    template = resolve_template(template_id)
    cleaned_markdown, removed_items = _clean_source_markdown(raw_markdown, template["id"])

    settings = effective_model_settings()
    model = settings["chat_model"]
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": schema_system_prompt(template)},
            {"role": "user", "content": schema_user_prompt(cleaned_markdown, domain, template, owner, removed_items)},
        ],
        "temperature": 0.1,
        "top_p": 0.8,
        "max_tokens": 2200,
    }
    try:
        async with httpx.AsyncClient(timeout=45, trust_env=False) as client:
            response = await client.post(
                f"{LITELLM_BASE_URL.rstrip('/')}/chat/completions",
                headers=litellm_headers(),
                json=body,
            )
    except Exception as exc:
        return _schema_fallback_result(
            cleaned_markdown, domain, template, owner, f"LiteLLM request failed: {exc}", removed_items
        )
    if response.status_code >= 400:
        if response.status_code >= 500:
            return _schema_fallback_result(
                cleaned_markdown,
                domain,
                template,
                owner,
                f"LiteLLM returned {response.status_code}: {response.text[:300]}",
                removed_items,
            )
        raise HTTPException(status_code=response.status_code, detail=response.text)

    payload = response.json()
    content = payload.get("choices", [{}])[0].get("message", {}).get("content") or ""
    try:
        result = _extract_json(content)
    except HTTPException as exc:
        return _schema_fallback_result(cleaned_markdown, domain, template, owner, str(exc.detail), removed_items)
    rewritten = str(result.get("rewritten_markdown") or "").strip()
    report = result.get("review_report") if isinstance(result.get("review_report"), dict) else {}
    if not rewritten:
        raise HTTPException(status_code=502, detail="model returned empty rewritten_markdown")
    rewritten = enforce_template(rewritten, template, domain, owner)
    validation = _validate_markdown(rewritten)
    report.setdefault("ready_for_active", False)
    report["ready_for_active"] = False
    report.setdefault("removed_irrelevant_content", removed_items)
    return jsonable(
        {
            "rewritten_markdown": rewritten,
            "review_report": report,
            "validation": validation,
            "model": model,
            "usage": payload.get("usage") or {},
            "selected_schema": {
                "id": template["id"],
                "label": template["label"],
                "type": template["type"],
            },
            "notes": {
                "write_policy": "preview_only_no_vault_write",
                "next_step": "人工确认后再保存到 20_Drafts；转正式前手动改 status=active, rag=true。",
            },
        }
    )
