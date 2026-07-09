from __future__ import annotations

import re
from io import BytesIO
from typing import Any

from fastapi import HTTPException, UploadFile
from pypdf import PdfReader

from utils import jsonable


MAX_PDF_BYTES = 30 * 1024 * 1024
MAX_PAGES = 80
MIN_TEXT_CHARS = 200


def _clean_text(text: str) -> str:
    text = text.replace("\x00", "")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{4,}", "\n\n\n", text)
    return text.strip()


async def extract_pdf(upload: UploadFile) -> dict[str, Any]:
    filename = upload.filename or "uploaded.pdf"
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="only .pdf files are supported")
    content = await upload.read()
    size = len(content)
    if not content:
        raise HTTPException(status_code=400, detail="empty pdf")
    if size > MAX_PDF_BYTES:
        raise HTTPException(status_code=400, detail=f"pdf is too large, max {MAX_PDF_BYTES // 1024 // 1024}MB")

    warnings: list[str] = []
    pages: list[dict[str, Any]] = []
    try:
        reader = PdfReader(BytesIO(content))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"cannot open pdf: {exc}") from exc
    if reader.is_encrypted:
        try:
            reader.decrypt("")
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"encrypted pdf is not supported: {exc}") from exc

    total_pages = len(reader.pages)
    if total_pages > MAX_PAGES:
        warnings.append(f"PDF 页数为 {total_pages}，第一版只抽取前 {MAX_PAGES} 页。")
    limit = min(total_pages, MAX_PAGES)

    for index in range(limit):
        page = reader.pages[index]
        try:
            text = _clean_text(page.extract_text() or "")
        except Exception:
            text = ""
        if not text:
            warnings.append(f"第 {index + 1} 页未抽取到文本，可能是扫描件或图片页。")
        pages.append({"page": index + 1, "chars": len(text), "text": text})

    total_chars = sum(page["chars"] for page in pages)
    if total_chars < MIN_TEXT_CHARS:
        warnings.append("抽取文本较少，可能是扫描型 PDF；第一版不做 OCR。")

    title = filename.rsplit(".", 1)[0]
    markdown_parts = [f"# {title}", "", f"> 来源 PDF：{filename}", ""]
    for page in pages:
        if not page["text"]:
            continue
        markdown_parts.extend([f"## 第 {page['page']} 页", "", page["text"], ""])
    extracted_markdown = "\n".join(markdown_parts).strip() + "\n"

    return jsonable(
        {
            "filename": filename,
            "bytes": size,
            "pages": total_pages,
            "extracted_pages": limit,
            "total_text_chars": total_chars,
            "warnings": warnings,
            "can_rewrite": total_chars >= MIN_TEXT_CHARS,
            "extracted_markdown": extracted_markdown,
            "page_summaries": [{"page": page["page"], "chars": page["chars"]} for page in pages],
            "notes": {
                "scope": "text_pdf_only_no_ocr",
                "next_step": "将 extracted_markdown 放入文档入库助手生成 draft 草稿。",
            },
        }
    )
