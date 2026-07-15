from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from config import SCHEMA_DOC, VAULT_PATH
from path_utils import safe_rel_path


SCHEMA_TEMPLATE_DIR = SCHEMA_DOC.parent / "schema-templates"
SCHEMA_TEMPLATE_SPECS = (
    {
        "id": "general",
        "label": "通用知识",
        "description": "稳定的内部知识、说明和通用参考资料。",
        "filename": "general-knowledge.md",
        "type": "knowledge_note",
    },
    {
        "id": "product",
        "label": "产品知识",
        "description": "产品规格、型号对应、兼容性和替代方案。",
        "filename": "product-knowledge.md",
        "type": "product_spec",
    },
    {
        "id": "enterprise_handbook",
        "label": "企业手册",
        "description": "员工手册、企业制度、部门职责和内部政策。",
        "filename": "enterprise-handbook.md",
        "type": "policy",
    },
    {
        "id": "technical",
        "label": "技术文档",
        "description": "架构、接口、配置、版本约束和故障排查。",
        "filename": "technical-document.md",
        "type": "knowledge_note",
    },
    {
        "id": "sop",
        "label": "流程 / SOP",
        "description": "标准操作、运维 Runbook、审批和应急处置流程。",
        "filename": "process-sop.md",
        "type": "runbook",
    },
)


def list_files(path: str = ".") -> dict[str, object]:
    target = safe_rel_path(path)
    if not target.exists() or not target.is_dir():
        raise HTTPException(status_code=404, detail="directory not found")
    entries = []
    for child in sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
        if child.name.startswith(".git"):
            continue
        if child.is_dir() or child.suffix.lower() == ".md":
            entries.append(
                {
                    "name": child.name,
                    "path": child.relative_to(VAULT_PATH).as_posix(),
                    "type": "dir" if child.is_dir() else "file",
                }
            )
    rel = target.relative_to(VAULT_PATH).as_posix() if target != VAULT_PATH else "."
    parent = None if target == VAULT_PATH else target.parent.relative_to(VAULT_PATH).as_posix()
    return {"path": rel, "parent": parent, "entries": entries}


def file_preview(path: str) -> dict[str, str]:
    target = safe_rel_path(path)
    if not target.exists() or not target.is_file() or target.suffix.lower() != ".md":
        raise HTTPException(status_code=404, detail="markdown file not found")
    content = target.read_text(encoding="utf-8", errors="replace")
    return {"path": target.relative_to(VAULT_PATH).as_posix(), "content": content[:100000]}


def _schema_templates() -> list[dict[str, str]]:
    templates: list[dict[str, str]] = []
    for spec in SCHEMA_TEMPLATE_SPECS:
        path = SCHEMA_TEMPLATE_DIR / spec["filename"]
        if not path.exists():
            continue
        templates.append(
            {
                "id": spec["id"],
                "label": spec["label"],
                "description": spec["description"],
                "type": spec["type"],
                "path": str(path),
                "content": path.read_text(encoding="utf-8", errors="replace"),
            }
        )
    return templates


def schema_template_by_id(template_id: str) -> dict[str, str]:
    normalized_id = template_id.strip() or "general"
    for template in _schema_templates():
        if template["id"] == normalized_id:
            return template
    raise HTTPException(status_code=400, detail=f"unknown schema template: {normalized_id}")


def schema_template() -> dict[str, Any]:
    templates = _schema_templates()

    default_template = "general"
    default_content = next(
        (item["content"] for item in templates if item["id"] == default_template),
        "schema template not found",
    )
    reference_content = (
        SCHEMA_DOC.read_text(encoding="utf-8", errors="replace")
        if SCHEMA_DOC.exists()
        else "schema document not found"
    )
    return {
        "default_template": default_template,
        "templates": templates,
        "content": default_content,
        "reference": {
            "path": str(SCHEMA_DOC),
            "content": reference_content,
        },
        "notes": [
            "所有模板默认生成 draft 且 rag=false，必须人工确认后才能进入正式知识库。",
            "模板中的 <domain_id>、维护人、日期、来源和正文占位符必须替换。",
            "领域扩展字段会保存在 frontmatter 中；通用必填字段仍由健康检查统一校验。",
        ],
    }
