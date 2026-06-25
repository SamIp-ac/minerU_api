"""Flatten MinerU analysis output into line-by-line type/content/bbox items."""

from __future__ import annotations

from typing import Any, Optional


def _stringify_content(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    if isinstance(value, list):
        parts = [_stringify_content(part) for part in value]
        joined = "\n".join(part for part in parts if part)
        return joined or None
    if isinstance(value, dict):
        for key in ("text", "content", "html", "body"):
            if key in value:
                return _stringify_content(value[key])
    text = str(value).strip()
    return text or None


def _content_from_content_list_item(item: dict) -> Optional[str]:
    for key in ("text", "table_body", "code_body", "img_path", "equation"):
        content = _stringify_content(item.get(key))
        if content:
            return content

    list_items = item.get("list_items")
    if list_items:
        return _stringify_content(list_items)

    return None


def _pick_bbox(*candidates: Any) -> Optional[list]:
    for candidate in candidates:
        if isinstance(candidate, list) and len(candidate) == 4:
            return candidate
    return None


def _lines_from_block_tree(
    blocks: list,
    *,
    page_idx: int,
    source: str,
    default_type: Optional[str] = None,
) -> list[dict]:
    lines: list[dict] = []

    for block in blocks or []:
        block_type = block.get("type") or default_type or "text"
        block_bbox = block.get("bbox")

        block_lines = block.get("lines")
        if block_lines:
            for line in block_lines:
                line_bbox = _pick_bbox(line.get("bbox"), block_bbox)
                for span in line.get("spans") or []:
                    content = _stringify_content(span.get("content"))
                    if not content:
                        continue
                    lines.append(
                        {
                            "type": span.get("type") or block_type,
                            "content": content,
                            "bbox": _pick_bbox(span.get("bbox"), line_bbox, block_bbox),
                            "page_idx": page_idx,
                            "source": source,
                        }
                    )
            continue

        content = _content_from_content_list_item(block)
        if content:
            lines.append(
                {
                    "type": block_type,
                    "content": content,
                    "bbox": block_bbox,
                    "page_idx": page_idx,
                    "source": source,
                }
            )

    return lines


def build_content_lines(
    analysis_results: dict,
    *,
    include_discarded: bool = True,
) -> list[dict]:
    """Build a flat, reading-order list of {type, content, bbox, page_idx} entries."""
    items: list[dict] = []

    for item in analysis_results.get("content_list_json") or []:
        items.append(
            {
                "type": item.get("type"),
                "content": _content_from_content_list_item(item),
                "bbox": item.get("bbox"),
                "page_idx": item.get("page_idx"),
                "source": "content_list",
            }
        )

    middle_json = analysis_results.get("middle_json") or {}
    for page in middle_json.get("pdf_info") or []:
        page_idx = page.get("page_idx", 0)

        if include_discarded:
            items.extend(
                _lines_from_block_tree(
                    page.get("discarded_blocks"),
                    page_idx=page_idx,
                    source="discarded",
                )
            )

    normalized: list[dict] = []
    for item in items:
        if item.get("content") is None and item.get("bbox") is None:
            continue
        entry = {
            "type": item.get("type"),
            "content": item.get("content"),
            "bbox": item.get("bbox"),
            "page_idx": item.get("page_idx"),
        }
        if item.get("source") != "content_list":
            entry["source"] = item["source"]
        normalized.append(entry)

    for line_index, item in enumerate(normalized):
        item["line_index"] = line_index

    return normalized
