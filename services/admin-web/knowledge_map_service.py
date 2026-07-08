from __future__ import annotations

import re
from collections import Counter
from pathlib import PurePosixPath
from typing import Any

from db import fetch_all, fetch_one
from domains_service import expected_domain_for_path
from utils import jsonable, string_list


SCHEMA_VERSION = "2026-07-kg-v1"

RELATION_TYPES: dict[str, dict[str, str]] = {
    "IN_DOMAIN": {"level": "strong", "source": "path/frontmatter"},
    "IN_FOLDER": {"level": "strong", "source": "path"},
    "FOLDER_IN_DOMAIN": {"level": "strong", "source": "path"},
    "HAS_TAG": {"level": "strong", "source": "frontmatter/tags"},
    "HAS_TYPE": {"level": "strong", "source": "frontmatter"},
    "IN_CATEGORY": {"level": "strong", "source": "frontmatter"},
    "ABOUT_PRODUCT_LINE": {"level": "strong", "source": "frontmatter"},
    "MENTIONS_SKU": {"level": "strong", "source": "frontmatter"},
    "HAS_ALIAS": {"level": "strong", "source": "frontmatter"},
    "COMPATIBLE_WITH": {"level": "strong", "source": "frontmatter"},
    "ALTERNATIVE_TO": {"level": "strong", "source": "frontmatter"},
    "HAS_LIMITATION": {"level": "strong", "source": "frontmatter"},
    "APPLIES_TO": {"level": "strong", "source": "frontmatter"},
    "LINKS_TO": {"level": "strong", "source": "wikilink"},
}


def _slug(value: Any) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"\s+", "-", text)
    text = re.sub(r"[^a-z0-9_.:/#@+\-\u4e00-\u9fff]+", "-", text)
    text = re.sub(r"-{2,}", "-", text).strip("-")
    return text or "unknown"


def _node_id(kind: str, value: Any) -> str:
    return f"{kind}:{_slug(value)}"


def _folder_for_path(path: str) -> str:
    parent = PurePosixPath(path).parent.as_posix()
    return parent if parent and parent != "." else "."


def _domain_for_doc(path: str, frontmatter: dict[str, Any]) -> str:
    domain = str(frontmatter.get("domain") or "").strip()
    if domain:
        return domain
    expected = expected_domain_for_path(path)
    return expected or "default"


def _title_for_doc(row: dict[str, Any]) -> str:
    frontmatter = row.get("frontmatter") or {}
    return str(frontmatter.get("title") or row.get("title") or PurePosixPath(row["path"]).stem)


def _doc_type(frontmatter: dict[str, Any]) -> str:
    return str(frontmatter.get("type") or "").strip()


def _first_values(frontmatter: dict[str, Any], keys: tuple[str, ...]) -> list[str]:
    values: list[str] = []
    for key in keys:
        values.extend(string_list(frontmatter.get(key)))
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        lowered = value.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        result.append(value)
    return result


def _load_documents() -> list[dict[str, Any]]:
    rows = fetch_all(
        """
        select
          d.path,
          d.title,
          d.frontmatter,
          d.tags,
          d.outlinks,
          d.status,
          d.product,
          d.applies_to,
          d.plans,
          coalesce(count(c.id), 0)::int as chunks
        from documents d
        left join chunks c on c.document_id = d.id
        group by
          d.path, d.title, d.frontmatter, d.tags, d.outlinks, d.status,
          d.product, d.applies_to, d.plans
        order by d.path
        """
    )
    for row in rows:
        if not isinstance(row.get("frontmatter"), dict):
            row["frontmatter"] = {}
    return rows


def _load_counts() -> dict[str, Any]:
    return fetch_one(
        """
        select
          (select count(*) from documents) as documents,
          (select count(*) from chunks) as chunks
        """
    )


def _build_graph(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    nodes: dict[str, dict[str, Any]] = {}
    edges: dict[tuple[str, str, str], dict[str, Any]] = {}
    doc_paths = {str(row["path"]) for row in rows}
    stem_to_path: dict[str, str] = {}

    for path in doc_paths:
        stem_to_path[PurePosixPath(path).stem] = path
        stem_to_path[path.removesuffix(".md")] = path

    def add_node(node_type: str, value: Any, label: str | None = None, metadata: dict[str, Any] | None = None) -> str:
        node_id = _node_id(node_type, value)
        if node_id not in nodes:
            nodes[node_id] = {
                "id": node_id,
                "type": node_type,
                "label": label or str(value),
                "metadata": metadata or {},
            }
        else:
            nodes[node_id]["metadata"].update(metadata or {})
        return node_id

    def add_edge(
        source: str,
        target: str,
        relation_type: str,
        source_path: str | None = None,
        method: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        if not source or not target or source == target:
            return
        key = (source, target, relation_type)
        if key not in edges:
            relation = RELATION_TYPES[relation_type]
            edges[key] = {
                "source": source,
                "target": target,
                "type": relation_type,
                "level": relation["level"],
                "method": method or relation["source"],
                "source_path": source_path,
                "metadata": metadata or {},
            }
        else:
            edges[key]["metadata"].update(metadata or {})

    for row in rows:
        path = str(row["path"])
        frontmatter: dict[str, Any] = row.get("frontmatter") or {}
        domain = _domain_for_doc(path, frontmatter)
        folder = _folder_for_path(path)
        title = _title_for_doc(row)
        status = str(row.get("status") or frontmatter.get("status") or "").strip()
        doc_id = add_node(
            "Document",
            path,
            title,
            {
                "path": path,
                "domain": domain,
                "folder": folder,
                "status": status,
                "chunks": int(row.get("chunks") or 0),
            },
        )
        domain_id = add_node("Domain", domain, domain, {"documents": 0})
        folder_id = add_node("Folder", folder, folder, {"domain": domain, "documents": 0})
        nodes[domain_id]["metadata"]["documents"] = int(nodes[domain_id]["metadata"].get("documents") or 0) + 1
        nodes[folder_id]["metadata"]["documents"] = int(nodes[folder_id]["metadata"].get("documents") or 0) + 1
        add_edge(doc_id, domain_id, "IN_DOMAIN", path)
        add_edge(doc_id, folder_id, "IN_FOLDER", path)
        add_edge(folder_id, domain_id, "FOLDER_IN_DOMAIN", path)

        tags = [*string_list(row.get("tags")), *string_list(frontmatter.get("tags"))]
        for tag in sorted({tag.strip("#") for tag in tags if tag}):
            tag_id = add_node("Tag", tag, tag)
            add_edge(doc_id, tag_id, "HAS_TAG", path)

        doc_type = _doc_type(frontmatter)
        if doc_type:
            type_id = add_node("DocType", doc_type, doc_type)
            add_edge(doc_id, type_id, "HAS_TYPE", path)

        for category in _first_values(frontmatter, ("category", "categories")):
            category_id = add_node("Category", category, category)
            add_edge(doc_id, category_id, "IN_CATEGORY", path)

        for line in _first_values(frontmatter, ("product_line", "product_lines")):
            line_id = add_node("ProductLine", line, line)
            add_edge(doc_id, line_id, "ABOUT_PRODUCT_LINE", path)

        skus = _first_values(frontmatter, ("sku", "skus", "product", "products"))
        if row.get("product"):
            skus.append(str(row["product"]))
        skus = _first_values({"sku": skus}, ("sku",))
        for sku in skus:
            sku_id = add_node("SKU", sku, sku, {"domain": domain})
            add_edge(doc_id, sku_id, "MENTIONS_SKU", path)

            for alias in _first_values(frontmatter, ("aliases", "alias")):
                alias_id = add_node("Alias", alias, alias)
                add_edge(sku_id, alias_id, "HAS_ALIAS", path)

            for compatible in _first_values(frontmatter, ("compatible_with", "compatibility")):
                compatible_id = add_node("SKU", compatible, compatible)
                add_edge(sku_id, compatible_id, "COMPATIBLE_WITH", path)

            for alternative in _first_values(frontmatter, ("alternatives", "alternative_to", "replacements")):
                alternative_id = add_node("SKU", alternative, alternative)
                add_edge(sku_id, alternative_id, "ALTERNATIVE_TO", path)

            for limitation in _first_values(frontmatter, ("limitations", "constraints", "notes")):
                limitation_id = add_node("Limitation", limitation, limitation)
                add_edge(sku_id, limitation_id, "HAS_LIMITATION", path)

            scenario_values = [
                *string_list(row.get("applies_to")),
                *string_list(row.get("plans")),
                *_first_values(frontmatter, ("applies_to", "plans", "scenarios", "use_cases")),
            ]
            for scenario in sorted({item for item in scenario_values if item}):
                scenario_id = add_node("Scenario", scenario, scenario)
                add_edge(sku_id, scenario_id, "APPLIES_TO", path)

        for link in string_list(row.get("outlinks")):
            clean = link.strip()
            target_path = clean if clean in doc_paths else stem_to_path.get(clean)
            if target_path:
                target_id = add_node("Document", target_path, PurePosixPath(target_path).stem, {"path": target_path})
                add_edge(doc_id, target_id, "LINKS_TO", path, method="wikilink")

    return list(nodes.values()), list(edges.values())


def _legacy_projection(rows: list[dict[str, Any]]) -> dict[str, Any]:
    folders: dict[str, dict[str, Any]] = {}
    domains: dict[str, dict[str, Any]] = {}
    documents: list[dict[str, Any]] = []
    products: dict[str, dict[str, Any]] = {}
    all_tags: Counter[str] = Counter()

    for row in rows:
        path = str(row["path"])
        frontmatter: dict[str, Any] = row.get("frontmatter") or {}
        domain = _domain_for_doc(path, frontmatter)
        folder = _folder_for_path(path)
        title = _title_for_doc(row)
        chunks = int(row.get("chunks") or 0)
        status = str(row.get("status") or frontmatter.get("status") or "").strip()
        skus = _first_values(frontmatter, ("sku", "skus", "product", "products"))
        if row.get("product"):
            skus.append(str(row["product"]))
        skus = _first_values({"sku": skus}, ("sku",))
        tags = sorted({tag.strip("#") for tag in [*string_list(row.get("tags")), *string_list(frontmatter.get("tags"))] if tag})

        folders.setdefault(folder, {"path": folder, "domain": domain, "documents": 0, "chunks": 0})
        folders[folder]["documents"] += 1
        folders[folder]["chunks"] += chunks

        domains.setdefault(domain, {"id": domain, "documents": 0, "chunks": 0, "products": set()})
        domains[domain]["documents"] += 1
        domains[domain]["chunks"] += chunks

        for tag in tags:
            all_tags[tag] += 1

        doc_ref = {"path": path, "title": title, "chunks": chunks, "status": status, "folder": folder, "domain": domain}
        documents.append({**doc_ref, "tags": tags, "sku": skus})

        for sku in skus:
            item = products.setdefault(
                sku,
                {
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
                },
            )
            item["documents"].append(doc_ref)
            item["aliases"].update(_first_values(frontmatter, ("aliases", "alias")))
            item["compatible_with"].update(_first_values(frontmatter, ("compatible_with", "compatibility")))
            item["alternatives"].update(_first_values(frontmatter, ("alternatives", "alternative_to", "replacements")))
            item["limitations"].update(_first_values(frontmatter, ("limitations", "constraints", "notes")))
            item["applies_to"].update(string_list(row.get("applies_to")))
            item["applies_to"].update(_first_values(frontmatter, ("applies_to", "scenarios", "use_cases")))
            item["plans"].update(string_list(row.get("plans")))
            item["plans"].update(_first_values(frontmatter, ("plans",)))
            item["tags"].update(tags)
            domains[domain]["products"].add(sku)

    return {
        "domains": [
            {**value, "products": sorted(value["products"])}
            for value in sorted(domains.values(), key=lambda item: item["id"])
        ],
        "folders": sorted(folders.values(), key=lambda item: item["path"]),
        "documents": documents,
        "products": [
            {
                **value,
                "aliases": sorted(value["aliases"]),
                "compatible_with": sorted(value["compatible_with"]),
                "alternatives": sorted(value["alternatives"]),
                "limitations": sorted(value["limitations"]),
                "applies_to": sorted(value["applies_to"]),
                "plans": sorted(value["plans"]),
                "tags": sorted(value["tags"]),
            }
            for value in sorted(products.values(), key=lambda item: item["sku"])
        ],
        "tags": [{"tag": tag, "documents": count} for tag, count in all_tags.most_common()],
    }


def knowledge_map_data() -> dict[str, Any]:
    rows = _load_documents()
    counts = _load_counts()
    nodes, edges = _build_graph(rows)
    legacy = _legacy_projection(rows)
    edge_counts = Counter(edge["type"] for edge in edges)
    node_counts = Counter(node["type"] for node in nodes)

    summary = {
        "documents": counts.get("documents") or len(rows),
        "chunks": counts.get("chunks") or sum(int(row.get("chunks") or 0) for row in rows),
        "domains": len(legacy["domains"]),
        "folders": len(legacy["folders"]),
        "products": len(legacy["products"]),
        "tags": len(legacy["tags"]),
        "nodes": len(nodes),
        "edges": len(edges),
        "node_types": dict(sorted(node_counts.items())),
        "edge_types": dict(sorted(edge_counts.items())),
    }
    policy = {
        "purpose": "展示 Wiki 中可解释、可追溯的显式知识关系。",
        "strong_sources": ["Markdown path", "frontmatter", "wikilink", "indexed metadata"],
        "vector_usage": "向量相似度只用于 RAG 检索，不作为知识图谱主干关系。",
        "llm_usage": "当前不使用 LLM 自动补边，避免把推断关系混入正式 Wiki 图谱。",
        "excluded": ["knowledge_gaps", "maintenance_suggestions", "vector_similarity_edges"],
    }

    return jsonable(
        {
            "schema": {"version": SCHEMA_VERSION, "relation_types": RELATION_TYPES},
            "summary": summary,
            "policy": policy,
            "nodes": sorted(nodes, key=lambda item: (item["type"], item["label"])),
            "edges": sorted(edges, key=lambda item: (item["type"], item["source"], item["target"])),
            **legacy,
        }
    )
