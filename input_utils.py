"""Input loading helpers that avoid MinerU's default 200 DPI / 3500px downscaling."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from io import BytesIO
from pathlib import Path
from typing import Optional

import pypdfium2 as pdfium
from PIL import Image, ImageOps

from mineru.utils.pdfium_guard import (
    get_pdfium_document_page_count,
    open_pdfium_document,
    pdfium_guard,
)

IMAGE_SUFFIXES = {".png", ".jpeg", ".jpg"}
PDF_SUFFIXES = {".pdf"}
ALLOWED_SUFFIXES = IMAGE_SUFFIXES | PDF_SUFFIXES

NATIVE_MAX_SIDE = 99999
PDF_RENDER_DPI = 300
IMAGE_WRAPPED_PDF_DPI = 72

_render_dpi: ContextVar[Optional[int]] = ContextVar("mineru_render_dpi", default=None)
_render_max_side: ContextVar[Optional[int]] = ContextVar("mineru_render_max_side", default=None)
_original_page_to_image = None


def _install_thread_safe_page_renderer() -> None:
    global _original_page_to_image
    if _original_page_to_image is not None:
        return

    import mineru.utils.pdf_reader as pdf_reader

    _original_page_to_image = pdf_reader.page_to_image

    def thread_safe_page_to_image(page, dpi=200, max_width_or_height=3500):
        use_dpi = _render_dpi.get()
        use_max = _render_max_side.get()
        if use_dpi is None:
            use_dpi = dpi
        if use_max is None:
            use_max = max_width_or_height
        return _original_page_to_image(page, dpi=use_dpi, max_width_or_height=use_max)

    pdf_reader.page_to_image = thread_safe_page_to_image


_install_thread_safe_page_renderer()


def image_bytes_to_pdf_bytes_native(image_bytes: bytes) -> bytes:
    """Wrap a raster image in PDF bytes without MinerU's 200 DPI save step."""
    image = Image.open(BytesIO(image_bytes))
    image = ImageOps.exif_transpose(image) or image
    if image.mode != "RGB":
        image = image.convert("RGB")

    pdf_buffer = BytesIO()
    image.save(pdf_buffer, format="PDF")
    return pdf_buffer.getvalue()


def read_input_file(path: str | Path) -> tuple[bytes, bool]:
    file_path = Path(path)
    suffix = file_path.suffix.lower()
    raw_bytes = file_path.read_bytes()

    if suffix in IMAGE_SUFFIXES:
        return image_bytes_to_pdf_bytes_native(raw_bytes), True
    if suffix in PDF_SUFFIXES:
        return raw_bytes, False
    raise ValueError(f"Unsupported file suffix: {suffix}")


def render_pdf_page_native(page, *, is_image_source: bool):
    dpi = IMAGE_WRAPPED_PDF_DPI if is_image_source else PDF_RENDER_DPI
    return _original_page_to_image(page, dpi=dpi, max_width_or_height=NATIVE_MAX_SIDE)


def load_pages_native(
    pdf_bytes: bytes,
    *,
    is_image_source: bool,
    start_page_id: int = 0,
    end_page_id: Optional[int] = None,
):
    pdf_doc = open_pdfium_document(pdfium.PdfDocument, pdf_bytes)
    page_count = get_pdfium_document_page_count(pdf_doc)
    if end_page_id is None or end_page_id < 0:
        end_page_id = page_count - 1
    end_page_id = min(end_page_id, page_count - 1)

    native_images = []
    with pdfium_guard():
        for page_index in range(start_page_id, end_page_id + 1):
            page = pdf_doc[page_index]
            pil_img, scale = render_pdf_page_native(page, is_image_source=is_image_source)
            native_images.append({"img_pil": pil_img, "scale": scale})

    return native_images, pdf_doc


@contextmanager
def native_resolution_mode(is_image_source: bool = False):
    """Per-request render settings safe for parallel worker threads."""
    render_dpi = IMAGE_WRAPPED_PDF_DPI if is_image_source else PDF_RENDER_DPI
    token_dpi = _render_dpi.set(render_dpi)
    token_max = _render_max_side.set(NATIVE_MAX_SIDE)
    try:
        yield
    finally:
        _render_dpi.reset(token_dpi)
        _render_max_side.reset(token_max)
