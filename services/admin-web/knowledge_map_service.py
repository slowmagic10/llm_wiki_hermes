from __future__ import annotations

from pathlib import Path
from typing import Any

from db import fetch_all
from domains_service import expected_domain_for_path
from utils import jsonable, string_list


def first_folder(path: str) -> str:
    parts = [part for part in path.split("/") if part]
    if "10_Knowledge" in parts:
        index = parts.index("10_Knowledge")
        if index + 1 < len(parts) - 1:
            return "/".join(parts[: index + 2])
    return "/".join(parts[:-1]) or "."


def frontmatter_domain(path: str, frontmatter: dict[str, Any]) -> str:
    domain = str(frontmatter.get("domain") or "").strip()
    if domain:
        return domain
    expected = expected_domain_for_path(path)
    return expected or "unknown"


def knowledge_map_data() -> dict[str, Any]:
    rows = fetch_all("""
        select
          d.path,
          d.title,
          d.product,
          d.tags,
          d.outlinks,
          d.status,
          d.applies_to,
          d.plans,
          d.frontmatter,
          d.updated_at,
          count(c.id)::int as chunks
        from documents d
        left join chunks c on c.document_id = d.id
        group by d.id
        order by d.path
    """)

    documents: list[dict[str, Any]] = []
    domains: dict[str, dict[str, Any]] = {}
    folders: dict[str, dict[str, Any]] = {}
    tags: dict[str, int] = {}
    products: dict[str, dict[str, Any]] = {}
    inlinks: dict[str, int] = {}
    path_set = {str(row.get("path")) for row in rows}

    for row in rows:
        path = str(row.get("path") or "")
        fm = row.get("frontmatter") if isinstance(row.get("frontmatter"), dict) else {}
        title = str(row.get("title") or fm.get("title") or Path(path).stem)
        domain = frontmatter_domain(path, fm)
        folder = first_folder(path)
        row_tags = string_list(row.get("tags") or fm.get("tags"))
        outlinks = string_list(row.get("outlinks"))
        chunks = int(row.get("chunks") or 0)

        for link in outlinks:
            inlinks[link] = inlinks.get(link, 0) + 1
        for tag in row_tags:
            tags[tag] = tags.get(tag, 0) + 1

        domains.setdefault(domain, {"id": domain, "documents": 0, "chunks": 0, "folders": set(), "products": set()})
        domains[domain]["documents"] += 1
        domains[domain]["chunks"] += chunks
        domains[domain]["folders"].add(folder)

        folders.setdefault(folder, {"path": folder, "domain": domain, "documents": 0, "chunks": 0})
        folders[folder]["documents"] += 1
        folders[folder]["chunks"] += chunks

        sku_values = string_list(fm.get("sku") or row.get("product") or fm.get("product"))
        aliases = string_list(fm.get("aliases"))
        compatible_with = string_list(fm.get("compatible_with"))
        alternatives = string_list(fm.get("alternatives"))
        limitations = string_list(fm.get("limitations"))
        applies_to = string_list(row.get("applies_to") or fm.get("applies_to"))
        plans = string_list(row.get("plans") or fm.get("plans"))
        source = string_list(fm.get("source") or fm.get("sources"))

        for sku in sku_values:
            products.setdefault(sku, {
                "sku": sku,
                "domain": domain,
                "documents": [],
                "aliases": set(),
                "compatible_with": set(),
                "alternatives": set(),
                "limitations": set(),
                "applies_to": set(),
                "plans": set(),
                "tags": set(),
            })
            item = products[sku]
            item["documents"].append({"path": path, "title": title, "chunks": chunks})
            item["aliases"].update(aliases)
            item["compatible_with"].update(compatible_with)
            item["alternatives"].update(alternatives)
            item["limitations"].update(limitations)
            item["applies_to"].update(applies_to)
            item["plans"].update(plans)
            item["tags"].update(row_tags)
            domains[domain]["products"].add(sku)

        documents.append({
            "path": path,
            "title": title,
            "domain": domain,
            "folder": folder,
            "status": row.get("status"),
            "chunks": chunks,
            "tags": row_tags,
            "outlinks": outlinks,
            "inlinks": 0,
            "sku": sku_values,
            "aliases": aliases,
            "compatible_with": compatible_with,
            "alternatives": alternatives,
            "limitations": limitations,
            "applies_to": applies_to,
            "plans": plans,
            "has_source": bool(source),
            "updated": row.get("updated_at"),
        })

    by_stem = {Path(path).stem: path for path in path_set}
    for doc in documents:
        count = 0
        for key, value in inlinks.items():
            if value <= 0:
                continue
            if key == doc["path"] or by_stem.get(key) == doc["path"] or key == Path(doc["path"]).stem:
                count += value
        doc["inlinks"] = count

    return jsonable({
        "summary": {
            "documents": len(documents),
            "chunks": sum(int(doc.get("chunks") or 0) for doc in documents),
            "domains": len(domains),
            "folders": len(folders),
            "products": len(products),
            "tags": len(tags),
        },
        "policy": {
            "purpose": "轻量知识图谱 / 知识地图，用于管理员理解 Wiki 结构和显式关系，不作为正式问答推理链路。",
            "strong_sources": ["markdown_path", "frontmatter", "wikilink", "indexed_chunks"],
            "vector_usage": "向量相似度不进入本图谱；后续如果做文档治理建议，应放到文档维护相关栏目。",
            "llm_usage": "LLM 不自动写回正式 Wiki，也不自动生成本图谱关系。",
        },
        "domains": [
            {
                **{key: value for key, value in item.items() if key not in {"folders", "products"}},
                "folders": sorted(item["folders"]),
                "products": sorted(item["products"]),
            }
            for item in sorted(domains.values(), key=lambda value: value["id"])
        ],
        "folders": sorted(folders.values(), key=lambda value: value["path"]),
        "products": [
            {
                "sku": sku,
                "domain": item["domain"],
                "documents": item["documents"],
                "aliases": sorted(item["aliases"]),
                "compatible_with": sorted(item["compatible_with"]),
                "alternatives": sorted(item["alternatives"]),
                "limitations": sorted(item["limitations"]),
                "applies_to": sorted(item["applies_to"]),
                "plans": sorted(item["plans"]),
                "tags": sorted(item["tags"]),
            }
            for sku, item in sorted(products.items(), key=lambda pair: pair[0].lower())
        ],
        "documents": documents,
        "tags": [{"name": name, "documents": count} for name, count in sorted(tags.items(), key=lambda pair: (-pair[1], pair[0]))],
    })
