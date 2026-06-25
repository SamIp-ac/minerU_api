"""MinerU 3.2.x streaming pipeline (doc_analyze_streaming)."""

from __future__ import annotations

import copy
import os
from typing import Optional

from loguru import logger

from input_utils import native_resolution_mode
from mineru.backend.pipeline.pipeline_analyze import doc_analyze_streaming
from mineru.backend.pipeline.pipeline_middle_json_mkcontent import union_make as pipeline_union_make
from mineru.cli.common import prepare_env
from mineru.data.data_reader_writer import FileBasedDataWriter
from mineru.utils.enum_class import MakeMode


def do_parse_v3(
    output_dir: str,
    pdf_file_names: list[str],
    pdf_bytes_list: list[bytes],
    is_image_source_list: list[bool],
    p_lang_list: list[str],
    parse_method: str,
    start_page_id: int,
    end_page_id: Optional[int],
    p_formula_enable: bool = True,
    p_table_enable: bool = True,
    f_make_md_mode: MakeMode = MakeMode.MM_MD,
):
    """MinerU 3.2.x path: doc_analyze_streaming with API render settings (400 DPI)."""
    from input_utils import load_pages_native

    if start_page_id != 0 or end_page_id is not None:
        logger.warning(
            "v3 streaming currently analyzes the full trimmed PDF bytes; "
            "page range metadata is applied before streaming starts."
        )

    image_writer_list: list[FileBasedDataWriter] = []
    local_image_dirs: list[str] = []
    for pdf_file_name in pdf_file_names:
        local_image_dir, _local_md_dir = prepare_env(output_dir, pdf_file_name, parse_method)
        local_image_dirs.append(local_image_dir)
        image_writer_list.append(FileBasedDataWriter(local_image_dir))

    rendered_pages_by_doc: dict[int, list[dict]] = {}
    for doc_index, (pdf_bytes, is_image_source) in enumerate(
        zip(pdf_bytes_list, is_image_source_list)
    ):
        images_list, _pdf_doc = load_pages_native(
            pdf_bytes,
            is_image_source=is_image_source,
            start_page_id=0,
            end_page_id=None,
        )
        rendered_pages_by_doc[doc_index] = [
            {"page_index": idx, "width": img["img_pil"].width, "height": img["img_pil"].height}
            for idx, img in enumerate(images_list)
        ]

    results: dict[int, dict] = {}

    def on_doc_ready(doc_index: int, model_list, middle_json, _ocr_enable: bool) -> None:
        pdf_file_name = pdf_file_names[doc_index]
        pdf_info = middle_json["pdf_info"]
        image_dir = os.path.basename(local_image_dirs[doc_index])
        md_content_str = pipeline_union_make(pdf_info, f_make_md_mode, image_dir)
        content_list = pipeline_union_make(pdf_info, MakeMode.CONTENT_LIST, image_dir)

        logger.info(f"MinerU v3 analysis complete for {pdf_file_name}")
        results[doc_index] = {
            "middle_json": middle_json,
            "model_json": copy.deepcopy(model_list),
            "content_list_json": content_list,
            "markdown": md_content_str,
            "pipeline": "v3_streaming",
            "rendered_pages": rendered_pages_by_doc.get(doc_index, []),
        }

    with native_resolution_mode(is_image_source=any(is_image_source_list)):
        doc_analyze_streaming(
            pdf_bytes_list,
            image_writer_list,
            p_lang_list,
            on_doc_ready,
            parse_method=parse_method,
            formula_enable=p_formula_enable,
            table_enable=p_table_enable,
        )

    if not results:
        raise RuntimeError("MinerU v3 analysis failed to produce any output.")

    return results[min(results.keys())]
