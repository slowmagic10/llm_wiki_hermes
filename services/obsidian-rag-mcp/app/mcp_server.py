from typing import Any

from mcp.server.fastmcp import FastMCP

from app.config import settings
from app.models_client import chat_complete
from app.retriever import _record_gap, search


mcp = FastMCP(
    "llm_wiki",
    instructions=(
        "Read-only enterprise wiki retrieval and answer generation. For knowledge, "
        "policy, product, compatibility, configuration, and FAQ questions, use search_llm_wiki and "
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


def _final_answer_is_invalid(answer: str) -> bool:
    text = (answer or "").strip()
    if not text:
        return True

    required_headings = ("结论：", "适用场景：", "注意事项：", "可替代方案：", "来源：")
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


def _fallback_answer(result: dict[str, Any]) -> str:
    if not result.get("answerable"):
        return _not_answerable_message()
    chunks = result.get("chunks") or []

    def section_text(*heading_keywords: str) -> str:
        for keyword in heading_keywords:
            for item in chunks:
                heading = " > ".join(item.get("heading_path") or [])
                if keyword not in heading:
                    continue
                text = str(item.get("text") or "").strip()
                if text:
                    return text
        return "未在正式 Wiki 中找到明确依据。"

    conclusion = section_text("一句话结论", "结论", "型号对应")
    scenarios = section_text("适用场景", "常用搭配", "推荐搭配", "使用场景", "型号对应")
    notes = section_text("限制条件", "注意事项", "兼容性", "售前确认点", "风险")
    alternatives = section_text("替代方案")

    lines = [
        "结论：",
        conclusion,
        "",
        "适用场景：",
        scenarios,
        "",
        "注意事项：",
        notes,
        "",
        "可替代方案：",
        alternatives,
    ]
    if result.get("citations"):
        lines.append("")
        lines.append("来源：")
        lines.extend(f"- {line}" for line in _source_lines(result)[:4])
    return "\n".join(lines).strip()


async def _build_final_answer(query: str, result: dict[str, Any]) -> str:
    if not result.get("answerable"):
        return _not_answerable_message()
    if settings.final_answer_mode != "llm":
        return _fallback_answer(result)

    sources = _source_block(result)
    source_lines = "\n".join(_source_lines(result)[:4])
    messages = [
        {
            "role": "system",
            "content": (
                "你是企业内部正式 Wiki 回答器。只能使用用户提供的来源内容回答。"
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
    if _final_answer_is_invalid(answer):
        return _fallback_answer(result)
    if _final_answer_has_no_basis(answer):
        return _not_answerable_message()
    return answer or _fallback_answer(result)


@mcp.tool(
    name="search_llm_wiki",
    title="Search LLM Wiki",
    description=(
        "Search and answer from the read-only Obsidian enterprise wiki. "
        "For final user responses, use the returned final_answer verbatim or nearly "
        "verbatim. Do not answer product knowledge questions from general model knowledge. "
        "The final_answer already includes citations."
    ),
    structured_output=True,
)
async def search_llm_wiki(
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
