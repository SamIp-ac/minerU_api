"""Streamlit demo for POST /analyze_layout/v3 with bbox overlay preview."""
# streamlit run app.py

from __future__ import annotations

import io
import json
from collections import defaultdict
from typing import Any, Optional

import pypdfium2 as pdfium
import requests
import streamlit as st
from PIL import Image, ImageDraw, ImageFont

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg"}
PDF_SUFFIXES = {".pdf"}

TYPE_COLORS = {
    "text": "#2563eb",
    "title": "#16a34a",
    "table": "#ea580c",
    "image": "#9333ea",
    "equation": "#dc2626",
    "header": "#0891b2",
    "footer": "#64748b",
    "page_number": "#94a3b8",
    "list": "#ca8a04",
    "code": "#7c3aed",
}
DEFAULT_COLOR = "#ef4444"


def _file_suffix(name: str) -> str:
    dot = name.rfind(".")
    return name[dot:].lower() if dot >= 0 else ""


def _scale_bbox(bbox: list[float], width: int, height: int) -> tuple[float, float, float, float]:
    x0, y0, x1, y1 = bbox
    max_coord = max(abs(x0), abs(y0), abs(x1), abs(y1))
    if max_coord <= 1000:
        return (
            x0 / 1000 * width,
            y0 / 1000 * height,
            x1 / 1000 * width,
            y1 / 1000 * height,
        )
    return x0, y0, x1, y1


def _content_preview(item: dict) -> str:
    for key in ("text", "table_body", "code_body", "img_path", "equation"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            text = value.strip()
            return text if len(text) <= 80 else text[:77] + "..."
    return item.get("type") or "block"


def _collect_page_items(analysis_results: dict) -> dict[int, list[dict]]:
    grouped: dict[int, list[dict]] = defaultdict(list)

    for item in analysis_results.get("content_list_json") or []:
        page_idx = item.get("page_idx")
        bbox = item.get("bbox")
        if page_idx is None or not bbox or len(bbox) != 4:
            continue
        grouped[int(page_idx)].append(item)

    return grouped


def _render_pdf_page(pdf_bytes: bytes, page_index: int, target_width: int, target_height: int) -> Image.Image:
    doc = pdfium.PdfDocument(pdf_bytes)
    try:
        page = doc[page_index]
        page_width, page_height = page.get_size()
        scale = target_width / page_width if page_width else 1.0
        bitmap = page.render(scale=scale)
        image = bitmap.to_pil().convert("RGB")
        if image.size != (target_width, target_height):
            image = image.resize((target_width, target_height), Image.Resampling.LANCZOS)
        return image
    finally:
        doc.close()


def _page_preview_image(
    upload_bytes: bytes,
    filename: str,
    page_index: int,
    target_width: int,
    target_height: int,
) -> Image.Image:
    suffix = _file_suffix(filename)
    if suffix in IMAGE_SUFFIXES:
        image = Image.open(io.BytesIO(upload_bytes)).convert("RGB")
        return image.resize((target_width, target_height), Image.Resampling.LANCZOS)
    if suffix in PDF_SUFFIXES:
        return _render_pdf_page(upload_bytes, page_index, target_width, target_height)
    raise ValueError(f"Unsupported preview type: {suffix}")


def _draw_bboxes(
    image: Image.Image,
    items: list[dict],
    *,
    show_labels: bool,
) -> Image.Image:
    canvas = image.copy()
    draw = ImageDraw.Draw(canvas)
    try:
        font = ImageFont.load_default()
    except OSError:
        font = None

    for item in items:
        bbox = item.get("bbox")
        if not bbox or len(bbox) != 4:
            continue

        x0, y0, x1, y1 = _scale_bbox([float(v) for v in bbox], canvas.width, canvas.height)
        block_type = str(item.get("type") or "unknown")
        color = TYPE_COLORS.get(block_type, DEFAULT_COLOR)
        draw.rectangle([x0, y0, x1, y1], outline=color, width=3)

        if show_labels:
            label = f"{block_type}: {_content_preview(item)}"
            text_y = max(0, y0 - 12)
            if font is not None:
                draw.text((x0 + 2, text_y), label, fill=color, font=font)
            else:
                draw.text((x0 + 2, text_y), label, fill=color)

    return canvas


def _call_analyze_v3(
    *,
    api_base: str,
    upload_bytes: bytes,
    filename: str,
    parse_method: str,
    lang: Optional[str],
    timeout_seconds: int,
) -> dict:
    url = api_base.rstrip("/") + "/analyze_layout/v3"
    params: dict[str, str] = {"parse_method": parse_method}
    if lang:
        params["lang"] = lang

    response = requests.post(
        url,
        params=params,
        files={"file": (filename, upload_bytes)},
        timeout=timeout_seconds,
    )
    if not response.ok:
        raise RuntimeError(f"HTTP {response.status_code}: {response.text[:2000]}")
    return response.json()


def main() -> None:
    st.set_page_config(page_title="MinerU v3 Layout Demo", layout="wide")
    st.title("MinerU `/analyze_layout/v3` demo")
    st.caption("Upload a PDF or image, call the API, preview pages with colored bbox overlays.")

    with st.sidebar:
        st.header("API settings")
        api_base = st.text_input("API base URL", value="http://localhost:8087")
        parse_method = st.selectbox("parse_method", ["auto", "ocr", "txt"], index=0)
        lang = st.text_input("lang (optional)", value="")
        timeout_seconds = st.number_input("Timeout (seconds)", min_value=60, max_value=3600, value=600, step=30)
        show_labels = st.checkbox("Draw bbox labels", value=True)
        st.markdown("**BBox colors**")
        for block_type, color in TYPE_COLORS.items():
            st.markdown(f"- `{block_type}`: <span style='color:{color}'>{color}</span>", unsafe_allow_html=True)

    uploaded = st.file_uploader(
        "Upload document",
        type=["pdf", "png", "jpg", "jpeg"],
        help="Same file types supported by the MinerU API.",
    )

    if uploaded is None:
        st.info("Upload a file to start.")
        return

    upload_bytes = uploaded.getvalue()
    suffix = _file_suffix(uploaded.name)

    col_preview, col_meta = st.columns([2, 1])
    with col_preview:
        st.subheader("Uploaded file preview")
        if suffix in IMAGE_SUFFIXES:
            st.image(upload_bytes, caption=uploaded.name, use_container_width=True)
        elif suffix in PDF_SUFFIXES:
            st.caption(f"{uploaded.name} — first page quick preview")
            try:
                quick = _render_pdf_page(upload_bytes, 0, 900, 1200)
                st.image(quick, use_container_width=True)
            except Exception as exc:
                st.warning(f"Could not render PDF preview: {exc}")
        else:
            st.error(f"Unsupported file type: {suffix}")

    with col_meta:
        st.subheader("Upload info")
        st.write(f"**Name:** {uploaded.name}")
        st.write(f"**Size:** {len(upload_bytes):,} bytes")
        st.write(f"**Type:** {suffix or 'unknown'}")

    if st.button("Run `/analyze_layout/v3`", type="primary", use_container_width=True):
        with st.spinner("Calling MinerU API (this may take several minutes)..."):
            try:
                result = _call_analyze_v3(
                    api_base=api_base,
                    upload_bytes=upload_bytes,
                    filename=uploaded.name,
                    parse_method=parse_method,
                    lang=lang.strip() or None,
                    timeout_seconds=int(timeout_seconds),
                )
            except Exception as exc:
                st.error(str(exc))
                return

        st.session_state["mineru_result"] = result
        st.session_state["upload_bytes"] = upload_bytes
        st.session_state["upload_name"] = uploaded.name

    result = st.session_state.get("mineru_result")
    if not result:
        return

    analysis = result.get("analysis_results") or {}
    rendered_pages = analysis.get("rendered_pages") or []
    grouped_items = _collect_page_items(analysis)

    st.success(
        f"Analysis complete — pipeline `{analysis.get('pipeline')}`, "
        f"{len(analysis.get('content_list_json') or [])} content blocks."
    )

    tab_overlay, tab_json = st.tabs(["BBox overlay", "Raw JSON"])

    with tab_overlay:
        if not rendered_pages:
            st.warning("No `rendered_pages` in response; cannot align bbox overlay.")
        else:
            for page in rendered_pages:
                page_index = int(page.get("page_index", 0))
                width = int(page["width"])
                height = int(page["height"])
                page_items = grouped_items.get(page_index, [])

                st.markdown(f"### Page {page_index + 1} — {width}×{height}px — {len(page_items)} boxes")
                try:
                    base_image = _page_preview_image(
                        st.session_state["upload_bytes"],
                        st.session_state["upload_name"],
                        page_index,
                        width,
                        height,
                    )
                    overlay_image = _draw_bboxes(base_image, page_items, show_labels=show_labels)
                except Exception as exc:
                    st.error(f"Failed to render page {page_index + 1}: {exc}")
                    continue

                left, right = st.columns([3, 2])
                with left:
                    st.image(overlay_image, caption=f"Page {page_index + 1} with bbox overlay", use_container_width=True)
                with right:
                    if page_items:
                        st.dataframe(
                            [
                                {
                                    "type": item.get("type"),
                                    "bbox": item.get("bbox"),
                                    "content": _content_preview(item),
                                }
                                for item in page_items
                            ],
                            use_container_width=True,
                            hide_index=True,
                        )
                    else:
                        st.info("No bbox items on this page in `content_list_json`.")

    with tab_json:
        st.json(result)


if __name__ == "__main__":
    main()
