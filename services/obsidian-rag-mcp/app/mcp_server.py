from typing import Any

from mcp.server.fastmcp import FastMCP

from app.models_client import chat_complete
from app.retriever import _record_gap, search


mcp = FastMCP(
    "sales_wiki",
    instructions=(
        "Read-only sales presales wiki retrieval and answer generation. For product, "
        "compatibility, configuration, and FAQ questions, use search_sales_wiki and "
        "answer from final_answer. Do not replace final_answer with general model "
        "knowledge. If answerable is false, say the official wiki has no reliable source."
    ),
    host="127.0.0.1",
    port=18081,
    streamable_http_path="/mcp",
    json_response=True,
)


def _source_block(result: dict[str, Any]) -> str:
    chunks = result.get("chunks") or []
    parts: list[str] = []
    for index, item in enumerate(chunks[:4], start=1):
        path = item.get("path") or ""
        heading = " > ".join(item.get("heading_path") or [])
        text = str(item.get("text") or "").strip()
        parts.append(f"[来源{index}] {path}#{heading}\n{text}")
    return "\n\n".join(parts)


def _source_lines(result: dict[str, Any]) -> list[str]:
    lines = []
    for index, citation in enumerate(result.get("citations") or [], start=1):
        path = citation.get("path") or ""
        heading = citation.get("heading") or ""
        score = citation.get("score")
        if isinstance(score, float):
            lines.append(f"[{index}] {path}# {heading}，score={score:.3f}")
        else:
            lines.append(f"[{index}] {path}# {heading}")
    return lines


def _not_answerable_message() -> str:
    return (
        "结论：正式 Wiki 中没有检索到足够可靠的来源，暂不能回答。\n\n"
        "适用场景：\n- 未在正式 Wiki 中找到明确依据。\n\n"
        "注意事项：\n- 该问题已按知识缺口记录，需人工补充或修订 Markdown 后再回答。\n\n"
        "可替代方案：\n- 请补充正式 Wiki 文档后重新同步索引。\n\n"
        "来源：\n- 无可靠来源"
    )


def _final_answer_has_no_basis(answer: str) -> bool:
    normalized = (answer or "").replace(" ", "")
    markers = (
        "结论：未在正式Wiki中找到明确依据",
        "来源：\n-未在正式Wiki中找到明确依据",
        "来源：\n-无可靠来源",
        "没有足够依据",
    )
    return any(marker in normalized for marker in markers)


def _mark_no_supported_answer(query: str, result: dict[str, Any]) -> None:
    result["answerable"] = False
    result["confidence"] = 0.0
    result["reason"] = "no_supported_answer"
    result["citations"] = []
    result["chunks"] = []
    _record_gap(query, "模型判断来源不足以回答")


def _fallback_answer(result: dict[str, Any]) -> str:
    if not result.get("answerable"):
        return _not_answerable_message()
    chunks = result.get("chunks") or []
    first_text = str(chunks[0].get("text") or "").strip() if chunks else "未在正式 Wiki 中找到明确依据。"
    lines = [
        "结论：",
        first_text,
        "",
        "适用场景：",
        "- 未在正式 Wiki 中找到明确依据。",
        "",
        "注意事项：",
        "- 未在正式 Wiki 中找到明确依据。",
        "",
        "可替代方案：",
        "- 未在正式 Wiki 中找到明确依据。",
    ]
    if result.get("citations"):
        lines.append("")
        lines.append("来源：")
        lines.extend(f"- {line}" for line in _source_lines(result)[:4])
    return "\n".join(lines).strip()


async def _build_final_answer(query: str, result: dict[str, Any]) -> str:
    if not result.get("answerable"):
        return _not_answerable_message()

    sources = _source_block(result)
    source_lines = "\n".join(_source_lines(result)[:4])
    messages = [
        {
            "role": "system",
            "content": (
                "你是企业内部销售/售前 Wiki 回答器。只能使用用户提供的来源内容回答。"
                "禁止使用来源以外的常识、规格、推测或补充说明。"
                "回答必须中文、客观、简洁。必须保留来源中出现的限制条件、版本号、替代料号。"
                "固定输出五个标题，顺序必须是：结论、适用场景、注意事项、可替代方案、来源。"
                "每个标题都必须出现。除结论外，其余标题下使用短项目符号。"
                "如果某个标题没有来源依据，必须写：未在正式 Wiki 中找到明确依据。"
                "来源部分只列出实际使用过的来源路径和标题，不要列无关来源。"
            ),
        },
        {
            "role": "user",
            "content": (
                f"问题：{query}\n\n"
                f"来源列表：\n{source_lines}\n\n"
                f"来源内容：\n{sources}\n\n"
                "请严格按以下格式回答，不要增加其他标题：\n"
                "结论：\n...\n\n"
                "适用场景：\n- ...\n\n"
                "注意事项：\n- ...\n\n"
                "可替代方案：\n- ...\n\n"
                "来源：\n- [1] path#heading\n\n"
                "规则：\n"
                "1. 结论必须直接回答问题。\n"
                "2. 适用场景只写来源明确支持的场景。\n"
                "3. 注意事项必须包含来源中的限制条件、固件版本、兼容要求。\n"
                "4. 可替代方案只写来源明确提到的替代料号或方案。\n"
                "5. 没有依据的栏目写：未在正式 Wiki 中找到明确依据。"
            ),
        },
    ]
    try:
        answer = await chat_complete(messages)
    except Exception:
        return _fallback_answer(result)
    if _final_answer_has_no_basis(answer):
        return _not_answerable_message()
    return answer or _fallback_answer(result)


@mcp.tool(
    name="search_sales_wiki",
    title="Search Sales Wiki",
    description=(
        "Search and answer from the read-only Obsidian sales/presales wiki. "
        "For final user responses, use the returned final_answer verbatim or nearly "
        "verbatim. Do not answer product knowledge questions from general model knowledge. "
        "The final_answer already includes citations."
    ),
    structured_output=True,
)
async def search_sales_wiki(
    query: str,
    product: str | None = None,
    tags: list[str] | None = None,
) -> dict[str, Any]:
    if not query or not query.strip():
        return {
            "answerable": False,
            "confidence": 0.0,
            "reason": "empty_query",
            "citations": [],
            "chunks": [],
            "final_answer": "问题为空，无法检索正式 Wiki。",
            "response_contract": "Use final_answer as the user-facing answer.",
        }
    clean_query = query.strip()
    result = await search(clean_query, product=product, tags=tags or [])
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
