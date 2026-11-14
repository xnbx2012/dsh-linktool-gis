"""PDF 文本提取 MCP 服务器

基于 PyMuPDF (fitz) 的 PDF 文本提取服务，支持中英文 PDF 文档。
"""

import json
import os
import traceback

import fitz  # PyMuPDF
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("pdf-reader")


@mcp.tool()
async def extract_pdf_text(pdf_path: str, pages: str = "") -> str:
    """Extract text content from a PDF file.

    Args:
        pdf_path: Absolute path to the PDF file.
        pages: Optional comma-separated page numbers or ranges to extract (1-based).
               Examples: "1,3,5" or "1-5" or "2-4,7". Leave empty to extract all pages.

    Returns:
        JSON string with extracted text and page information.
    """
    try:
        if not os.path.exists(pdf_path):
            return json.dumps(
                {"success": False, "error": f"文件不存在: {pdf_path}"},
                ensure_ascii=False,
            )

        if not pdf_path.lower().endswith(".pdf"):
            return json.dumps(
                {"success": False, "error": f"不是 PDF 文件: {pdf_path}"},
                ensure_ascii=False,
            )

        doc = fitz.open(pdf_path)
        total_pages = len(doc)

        # 解析页码范围
        page_numbers = _parse_page_range(pages, total_pages)

        result_pages = []
        full_text_parts = []
        for page_num in page_numbers:
            page = doc[page_num - 1]  # fitz 使用 0-based 索引
            text = page.get_text("text")
            result_pages.append(
                {"page": page_num, "text": text, "char_count": len(text)}
            )
            full_text_parts.append(f"--- 第 {page_num} 页 ---\n{text}")

        doc.close()

        return json.dumps(
            {
                "success": True,
                "result": {
                    "total_pages": total_pages,
                    "extracted_pages": len(page_numbers),
                    "pages": result_pages,
                    "full_text": "\n\n".join(full_text_parts),
                },
            },
            ensure_ascii=False,
            indent=2,
        )

    except Exception as e:
        return json.dumps(
            {
                "success": False,
                "error": str(e),
                "traceback": traceback.format_exc(),
            },
            ensure_ascii=False,
        )


@mcp.tool()
async def get_pdf_info(pdf_path: str) -> str:
    """Get metadata and basic information about a PDF file.

    Args:
        pdf_path: Absolute path to the PDF file.

    Returns:
        JSON string with PDF metadata including page count, title, author, etc.
    """
    try:
        if not os.path.exists(pdf_path):
            return json.dumps(
                {"success": False, "error": f"文件不存在: {pdf_path}"},
                ensure_ascii=False,
            )

        doc = fitz.open(pdf_path)
        metadata = doc.metadata
        file_size = os.path.getsize(pdf_path)

        result = {
            "file_path": pdf_path,
            "file_size_bytes": file_size,
            "file_size_mb": round(file_size / (1024 * 1024), 2),
            "total_pages": len(doc),
            "title": metadata.get("title", ""),
            "author": metadata.get("author", ""),
            "subject": metadata.get("subject", ""),
            "creator": metadata.get("creator", ""),
            "producer": metadata.get("producer", ""),
            "creation_date": metadata.get("creationDate", ""),
            "mod_date": metadata.get("modDate", ""),
            "encrypted": doc.is_encrypted,
            "pdf_version": doc.pdf_version() if hasattr(doc, "pdf_version") else "",
        }

        doc.close()

        return json.dumps(
            {"success": True, "result": result},
            ensure_ascii=False,
            indent=2,
        )

    except Exception as e:
        return json.dumps(
            {
                "success": False,
                "error": str(e),
                "traceback": traceback.format_exc(),
            },
            ensure_ascii=False,
        )


def _parse_page_range(pages_str: str, total_pages: int) -> list[int]:
    """Parse page range string into a list of 1-based page numbers.

    Args:
        pages_str: Comma-separated page numbers or ranges (e.g. "1,3,5-8").
        total_pages: Total number of pages in the document.

    Returns:
        Sorted list of unique 1-based page numbers.
    """
    if not pages_str or not pages_str.strip():
        return list(range(1, total_pages + 1))

    page_set = set()
    for part in pages_str.split(","):
        part = part.strip()
        if "-" in part:
            start_str, end_str = part.split("-", 1)
            start = max(1, int(start_str.strip()))
            end = min(total_pages, int(end_str.strip()))
            page_set.update(range(start, end + 1))
        else:
            num = int(part)
            if 1 <= num <= total_pages:
                page_set.add(num)

    return sorted(page_set)


def main():
    """Run the MCP server."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
