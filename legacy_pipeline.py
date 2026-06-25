"""Restore MinerU 2.0.6 doc_analyze flow on top of mineru 3.2.x libraries."""

from __future__ import annotations

import os

from loguru import logger

from input_utils import load_pages_native
from mineru.backend.pipeline.pipeline_analyze import batch_image_analyze
from mineru.utils.pdf_classify import classify


def doc_analyze(
    pdf_bytes_list,
    lang_list,
    is_image_source_list,
    parse_method: str = "auto",
    formula_enable=True,
    table_enable=True,
    start_page_id: int = 0,
    end_page_id=None,
):
    """
    Drop-in replacement for MinerU 2.0.6 pipeline_analyze.doc_analyze.

    Uses API page loading (400 DPI, 3500px long-side cap).
    """
    min_batch_inference_size = int(os.environ.get("MINERU_MIN_BATCH_INFERENCE_SIZE", 100))

    all_pages_info = []
    all_image_lists = []
    all_pdf_docs = []
    ocr_enabled_list = []

    for pdf_idx, pdf_bytes in enumerate(pdf_bytes_list):
        ocr_enable = parse_method == "ocr" or (
            parse_method == "auto" and classify(pdf_bytes) == "ocr"
        )
        ocr_enabled_list.append(ocr_enable)
        lang = lang_list[pdf_idx]

        images_list, pdf_doc = load_pages_native(
            pdf_bytes,
            is_image_source=is_image_source_list[pdf_idx],
            start_page_id=start_page_id,
            end_page_id=end_page_id,
        )
        all_image_lists.append(images_list)
        all_pdf_docs.append(pdf_doc)

        for page_idx, img_dict in enumerate(images_list):
            all_pages_info.append((pdf_idx, page_idx, img_dict["img_pil"], ocr_enable, lang))

    images_with_extra_info = [(info[2], info[3], info[4]) for info in all_pages_info]
    batch_size = min_batch_inference_size
    batch_images = [
        images_with_extra_info[i : i + batch_size]
        for i in range(0, len(images_with_extra_info), batch_size)
    ]

    results = []
    processed_images_count = 0
    for index, batch_image in enumerate(batch_images):
        processed_images_count += len(batch_image)
        logger.info(
            f"[v2] Batch {index + 1}/{len(batch_images)}: "
            f"{processed_images_count} pages/{len(images_with_extra_info)} pages"
        )
        batch_results = batch_image_analyze(batch_image, formula_enable, table_enable)
        results.extend(batch_results)

    infer_results = [[] for _ in range(len(pdf_bytes_list))]
    for i, page_info in enumerate(all_pages_info):
        pdf_idx, page_idx, pil_img, _, _ = page_info
        page_info_dict = {
            "page_no": page_idx,
            "width": pil_img.width,
            "height": pil_img.height,
        }
        infer_results[pdf_idx].append(
            {"layout_dets": results[i], "page_info": page_info_dict}
        )

    return infer_results, all_image_lists, all_pdf_docs, lang_list, ocr_enabled_list
