from typing import Any

from mcp.server.fastmcp import FastMCP

from app.config import settings
from app.models_client import chat_complete
from app.profiles import resolve_profile
from app.retriever import _record_gap, search


mcp = FastMCP(
    "llm_wiki",
    instructions=(
        "Read-only enterprise wiki retrieval and answer generation. For knowledge, "
        "policy, product, compatibility, configuration, and FAQ questions, use search_llm_wiki and "
        "answer from final_answer. Pass domain when a domain-specific hook is used. "
        "Do not replace final_answer with general model knowledge. If answerable is false, "
        "say the official wiki has no reliable source."
    ),
    host="127.0.0.1",
    port=18081,
    streamable_http_path="/mcp",
    json_response=True,
)


def _answer_config(result: dict[str, Any]) -> dict[str, Any]:
    return resolve_profile(result.get("domain"), result.get("profile"))["answer"]


def _source_block(result: dict[str, Any], max_sources: int) -> str:
    chunks = result.get("chunks") or []
    parts: list[str] = []
    for index, item in enumerate(chunks[:max_sources], start=1):
        path = item.get("path") or ""
        heading = " > ".join(item.get("heading_path") or [])
        text = str(item.get("text") or "").strip()
        parts.append(f"[来源{index}] {path}#{heading}\n{text}")
    return "\n\n".join(parts)


def _source_lines(result: dict[str, Any], max_sources: int | None = None) -> list[str]:
    citations = result.get("citations") or []
    if max_sources is not None:
        citations = citations[:max_sources]
    lines = []
    for index, citation in enumerate(citations, start=1):
        path = citation.get("path") or ""
        heading = citation.get("heading") or ""
        score = citation.get("score")
        if isinstance(score, float):
            lines.append(f"[{index}] {path}# {heading}，score={score:.3f}")
        else:
            lines.append(f"[{index}] {path}# {heading}")
    return lines


def _sections(answer_config: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for item in (answer_config.get("sections") or []) if isinstance(item, dict)]


def _not_answerable_message(answer_config: dict[str, Any]) -> str:
    no_basis = str(answer_config.get("no_basis_text") or "未在正式 Wiki 中找到明确依据。")
    lines: list[str] = []
    for section in _sections(answer_config):
        label = str(section.get("label") or "").strip()
        lines.append(f"{label}：")
        if section.get("kind") == "sources":
            lines.append("- 无可靠来源")
        else:
            lines.append(no_basis)
        lines.append("")
    return "\n".join(lines).strip()


def _final_answer_has_no_basis(answer: str) -> bool:
    normalized = (answer or "").replace(" ", "")
    markers = (
        "结论：未在正式Wiki中找到明确依据",
        "来源：\n-未在正式Wiki中找到明确依据",
        "来源：\n-无可靠来源",
        "没有足够依据",
    )
    return any(marker in normalized for marker in markers)


def _final_answer_is_invalid(answer: str, answer_config: dict[str, Any]) -> bool:
    text = (answer or "").strip()
    if not text:
        return True

    required_headings = tuple(f"{section['label']}：" for section in _sections(answer_config))
    if not all(heading in text for heading in required_headings):
        return True

    zero_count = text.count("0")
    chinese_count = sum(1 for char in text if "\u4e00" <= char <= "\u9fff")
    if len(text) >= 80 and zero_count / max(len(text), 1) > 0.5 and chinese_count < 10:
        return True

    return False


def _mark_no_supported_answer(query: str, result: dict[str, Any]) -> None:
    result["answerable"] = False
    result["confidence"] = 0.0
    result["reason"] = "no_supported_answer"
    result["citations"] = []
    result["chunks"] = []
    _record_gap(query, "模型判断来源不足以回答")


def _section_text(chunks: list[dict[str, Any]], headings: list[str], no_basis: str) -> str:
    for keyword in headings:
        for item in chunks:
            heading = " > ".join(item.get("heading_path") or [])
            if keyword not in heading:
                continue
            text = str(item.get("text") or "").strip()
            if text:
                return text
    return no_basis


def _fallback_answer(result: dict[str, Any], answer_config: dict[str, Any]) -> str:
    if not result.get("answerable"):
        return _not_answerable_message(answer_config)

    chunks = result.get("chunks") or []
    no_basis = str(answer_config.get("no_basis_text") or "未在正式 Wiki 中找到明确依据。")
    max_sources = int(answer_config.get("max_sources") or 4)
    lines: list[str] = []
    for section in _sections(answer_config):
        label = str(section.get("label") or "").strip()
        lines.append(f"{label}：")
        if section.get("kind") == "sources":
            source_lines = _source_lines(result, max_sources)
            lines.extend(f"- {line}" for line in source_lines)
            if not source_lines:
                lines.append("- 无可靠来源")
        else:
            headings = [str(value) for value in (section.get("source_headings") or [])]
            lines.append(_section_text(chunks, headings, no_basis))
        lines.append("")
    return "\n".join(lines).strip()


def _format_template(answer_config: dict[str, Any]) -> str:
    blocks: list[str] = []
    for section in _sections(answer_config):
        label = str(section.get("label") or "").strip()
        placeholder = "- ..." if section.get("kind") == "sources" or section.get("key") != "conclusion" else "..."
        blocks.append(f"{label}：\n{placeholder}")
    return "\n\n".join(blocks)


async def _build_final_answer(query: str, result: dict[str, Any]) -> str:
    answer_config = _answer_config(result)
    if not result.get("answerable"):
        return _not_answerable_message(answer_config)
    if settings.final_answer_mode != "llm":
        return _fallback_answer(result, answer_config)

    max_sources = int(answer_config.get("max_sources") or 4)
    sources = _source_block(result, max_sources)
    source_lines = "\n".join(_source_lines(result, max_sources))
    labels = "、".join(str(item.get("label") or "") for item in _sections(answer_config))
    instructions = "\n".join(
        f"{index}. {item}" for index, item in enumerate(answer_config.get("instructions") or [], start=1)
    )
    format_template = _format_template(answer_config)
    no_basis = str(answer_config.get("no_basis_text") or "未在正式 Wiki 中找到明确依据。")
    messages = [
        {
            "role": "system",
            "content": (
                "你是企业内部正式 Wiki 回答器。只能使用用户提供的来源内容回答。"
                f"必须按以下栏目及顺序输出：{labels}。"
                f"\n领域回答规则：\n{instructions}"
            ),
        },
        {
            "role": "user",
            "content": (
                f"问题：{query}\n\n"
                f"来源列表：\n{source_lines}\n\n"
                f"来源内容：\n{sources}\n\n"
                f"请严格按以下格式回答，不要增加其他标题：\n{format_template}\n\n"
                f"没有来源依据的栏目必须写：{no_basis}"
            ),
        },
    ]
    try:
        answer = await chat_complete(messages, max_tokens=int(answer_config.get("max_tokens") or 900))
    except Exception:
        return _fallback_answer(result, answer_config)
    if _final_answer_is_invalid(answer, answer_config):
        return _fallback_answer(result, answer_config)
    if _final_answer_has_no_basis(answer):
        return _not_answerable_message(answer_config)
    return answer or _fallback_answer(result, answer_config)


@mcp.tool(
    name="search_llm_wiki",
    title="Search LLM Wiki",
    description=(
        "Search and answer from the read-only Obsidian enterprise wiki. "
        "Use domain to select an isolated knowledge domain; its registered profile controls "
        "retrieval thresholds and answer format. For final user responses, use final_answer "
        "verbatim or nearly verbatim. Do not answer from general model knowledge."
    ),
    structured_output=True,
)
async def search_llm_wiki(
    query: str,
    product: str | None = None,
    tags: list[str] | None = None,
    domain: str | None = None,
    profile: str | None = None,
) -> dict[str, Any]:
    if not query or not query.strip():
        return {
            "answerable": False,
            "confidence": 0.0,
            "reason": "empty_query",
            "domain": domain or "default",
            "profile": profile,
            "citations": [],
            "chunks": [],
            "final_answer": "问题为空，无法检索正式 Wiki。",
            "response_contract": "Use final_answer as the user-facing answer.",
        }
    clean_query = query.strip()
    result = await search(
        clean_query,
        product=product,
        tags=tags or [],
        domain=domain,
        profile=profile,
    )
    result["final_answer"] = await _build_final_answer(clean_query, result)
    if _final_answer_has_no_basis(result["final_answer"]):
        _mark_no_supported_answer(clean_query, result)
    result["response_contract"] = (
        "Use final_answer as the user-facing answer. Do not add facts that are not "
        "present in citations or chunks."
    )
    return result


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
