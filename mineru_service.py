# mineru_service.py
import asyncio
import concurrent.futures
import copy
import json
import os
import tempfile
from pathlib import Path
from typing import Optional

import uvicorn
from fastapi import FastAPI, UploadFile, File, HTTPException, Query, Response
from loguru import logger

from mineru.backend.pipeline.model_json_to_middle_json import result_to_middle_json as pipeline_result_to_middle_json
from mineru.backend.pipeline.pipeline_middle_json_mkcontent import union_make as pipeline_union_make
from mineru.cli.common import convert_pdf_bytes_to_bytes, prepare_env
from mineru.data.data_reader_writer import FileBasedDataWriter
from mineru.utils.enum_class import MakeMode

from input_utils import ALLOWED_SUFFIXES, MAX_RENDER_SIDE, PDF_RENDER_DPI, read_input_file
from flat_output import build_content_lines
from legacy_pipeline import doc_analyze as pipeline_doc_analyze_v2
from modern_pipeline import do_parse_v3

convert_pdf_bytes_to_bytes_by_pypdfium2 = convert_pdf_bytes_to_bytes

PREPROCESSING_NOTE = (
    "API render DPI override is enabled for both v2 and v3 routes. "
    f"Image uploads are wrapped to PDF at {PDF_RENDER_DPI} DPI "
    "(EXIF transpose, RGB, quality=95). "
    f"All pages render at {PDF_RENDER_DPI} DPI with a {MAX_RENDER_SIDE}px long-side cap. "
    "MinerU 3.2.1 default is 200 DPI; internal ML models may still resize tensors during inference."
)

PIPELINE_V2_NOTE = (
    "MinerU 2.0.6-compatible pipeline on top of mineru 3.2.x libraries: "
    "doc_analyze (batch) -> result_to_middle_json -> union_make."
)

PIPELINE_V3_NOTE = (
    "MinerU 3.2.1 default pipeline: doc_analyze_streaming (processing-window) -> union_make. "
    "Different orchestration and post-processing from v2; output schema is similar but not identical."
)

MAX_CONCURRENT_TASKS = max(1, int(os.getenv("MINERU_MAX_CONCURRENT_TASKS", "2")))
_analysis_semaphore = asyncio.Semaphore(MAX_CONCURRENT_TASKS)
_active_tasks = 0
_active_tasks_lock = asyncio.Lock()
_thread_pool: concurrent.futures.ThreadPoolExecutor | None = None

CONCURRENCY_NOTE = (
    f"Parallel requests are supported up to {MAX_CONCURRENT_TASKS} concurrent analysis tasks "
    f"(MINERU_MAX_CONCURRENT_TASKS). Additional requests wait in queue. "
    "Heavy ML inference runs in worker threads so the API can accept multiple uploads at once."
)

LANG_QUERY_DESCRIPTION = (
    "Optional OCR language hint for the entire document (not per region/block). "
    "Omit this parameter, or send an empty value (`lang=`), for multilingual or mixed-language pages; "
    "MinerU will use its default OCR path without a language-specific model hint. "
    "Set a value only when the document is mostly one language and you want to bias OCR accuracy "
    "(e.g. ch, en, korean, japan, ch_server, arabic, devanagari)."
)

app = FastAPI(
    title="MinerU Document Analysis Service",
    description=(
        "Layout analysis API with two pipeline versions for comparison. "
        + PREPROCESSING_NOTE
        + " "
        + CONCURRENCY_NOTE
    ),
    version="1.5.0",
)

ALLOWED_EXTENSIONS = ALLOWED_SUFFIXES


def normalize_lang(lang: Optional[str]) -> Optional[str]:
    if lang is None:
        return None
    normalized = lang.strip()
    return normalized or None


def _validate_extension(filename: str) -> None:
    file_extension = Path(filename).suffix.lower()
    if file_extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"File type '{file_extension}' not supported. Please upload one of: {sorted(ALLOWED_EXTENSIONS)}",
        )


def do_parse_v2(
    output_dir: str,
    pdf_file_names: list[str],
    pdf_bytes_list: list[bytes],
    is_image_source_list: list[bool],
    p_lang_list: list[Optional[str]],
    parse_method: str,
    start_page_id: int,
    end_page_id: Optional[int],
    p_formula_enable: bool = True,
    p_table_enable: bool = True,
    f_make_md_mode: MakeMode = MakeMode.MM_MD,
):
    for idx, pdf_bytes in enumerate(pdf_bytes_list):
        pdf_bytes_list[idx] = convert_pdf_bytes_to_bytes_by_pypdfium2(
            pdf_bytes, start_page_id, end_page_id
        )

    infer_results, all_image_lists, all_pdf_docs, lang_list, ocr_enabled_list = pipeline_doc_analyze_v2(
        pdf_bytes_list,
        p_lang_list,
        is_image_source_list,
        parse_method=parse_method,
        formula_enable=p_formula_enable,
        table_enable=p_table_enable,
        start_page_id=0,
        end_page_id=None,
    )

    for idx, model_list in enumerate(infer_results):
        model_json = copy.deepcopy(model_list)
        pdf_file_name = pdf_file_names[idx]
        local_image_dir, _local_md_dir = prepare_env(output_dir, pdf_file_name, parse_method)
        image_writer = FileBasedDataWriter(local_image_dir)

        images_list = all_image_lists[idx]
        pdf_doc = all_pdf_docs[idx]
        lang = lang_list[idx]
        ocr_enable = ocr_enabled_list[idx]

        middle_json = pipeline_result_to_middle_json(
            model_list,
            images_list,
            pdf_doc,
            image_writer,
            lang,
            ocr_enable,
            p_formula_enable,
        )
        pdf_info = middle_json["pdf_info"]
        image_dir = str(os.path.basename(local_image_dir))
        md_content_str = pipeline_union_make(pdf_info, f_make_md_mode, image_dir)
        content_list = pipeline_union_make(pdf_info, MakeMode.CONTENT_LIST, image_dir)

        logger.info(f"MinerU v2 analysis complete for {pdf_file_name}")
        return {
            "middle_json": middle_json,
            "model_json": model_json,
            "content_list_json": content_list,
            "markdown": md_content_str,
            "pipeline": "v2_legacy_doc_analyze",
            "rendered_pages": [
                {"page_index": page_idx, "width": img["img_pil"].width, "height": img["img_pil"].height}
                for page_idx, img in enumerate(images_list)
            ],
        }

    raise RuntimeError("MinerU v2 analysis failed to produce any output.")


def _run_analysis_sync(
    *,
    temp_dir: str,
    filename: str,
    pdf_bytes: bytes,
    is_image_source: bool,
    lang: Optional[str],
    parse_method: str,
    start_page_id: int,
    end_page_id: Optional[int],
    pipeline_version: str,
):
    file_name_list = [Path(filename).stem]
    pdf_bytes_list = [pdf_bytes]
    is_image_source_list = [is_image_source]
    lang_list = [lang]

    if pipeline_version == "v2":
        return do_parse_v2(
            output_dir=temp_dir,
            pdf_file_names=file_name_list,
            pdf_bytes_list=pdf_bytes_list,
            is_image_source_list=is_image_source_list,
            p_lang_list=lang_list,
            parse_method=parse_method,
            start_page_id=start_page_id,
            end_page_id=end_page_id,
        )

    if pipeline_version == "v3":
        trimmed_bytes = convert_pdf_bytes_to_bytes_by_pypdfium2(
            pdf_bytes, start_page_id, end_page_id
        )
        return do_parse_v3(
            output_dir=temp_dir,
            pdf_file_names=file_name_list,
            pdf_bytes_list=[trimmed_bytes],
            is_image_source_list=is_image_source_list,
            p_lang_list=lang_list,
            parse_method=parse_method,
            start_page_id=start_page_id,
            end_page_id=end_page_id,
        )

    raise ValueError(f"Unknown pipeline version: {pipeline_version}")


@app.on_event("startup")
async def configure_thread_pool() -> None:
    global _thread_pool
    loop = asyncio.get_running_loop()
    _thread_pool = concurrent.futures.ThreadPoolExecutor(max_workers=MAX_CONCURRENT_TASKS)
    loop.set_default_executor(_thread_pool)
    logger.info(f"MinerU API ready: max_concurrent_tasks={MAX_CONCURRENT_TASKS}")


@app.on_event("shutdown")
async def shutdown_thread_pool() -> None:
    global _thread_pool
    if _thread_pool is not None:
        _thread_pool.shutdown(wait=True, cancel_futures=False)
        _thread_pool = None


@app.get("/health", summary="Service health and concurrency status")
async def health_check():
    return {
        "status": "ok",
        "max_concurrent_tasks": MAX_CONCURRENT_TASKS,
        "active_tasks": _active_tasks,
        "available_slots": _analysis_semaphore._value,
    }


async def _execute_analysis(
    *,
    file: UploadFile,
    lang: Optional[str],
    parse_method: str,
    start_page_id: int,
    end_page_id: Optional[int],
    pipeline_version: str,
) -> tuple[str, Optional[str], dict]:
    _validate_extension(file.filename)

    async with _analysis_semaphore:
        global _active_tasks
        async with _active_tasks_lock:
            _active_tasks += 1

        temp_dir = tempfile.mkdtemp()
        temp_file_path = os.path.join(temp_dir, file.filename)
        try:
            with open(temp_file_path, "wb") as f:
                f.write(await file.read())

            logger.info(
                f"[{pipeline_version}] queued task started for '{file.filename}' "
                f"(active={_active_tasks}, max={MAX_CONCURRENT_TASKS})"
            )
            pdf_bytes, is_image_source = read_input_file(temp_file_path)
            resolved_lang = normalize_lang(lang)

            analysis_results = await asyncio.to_thread(
                _run_analysis_sync,
                temp_dir=temp_dir,
                filename=file.filename,
                pdf_bytes=pdf_bytes,
                is_image_source=is_image_source,
                lang=resolved_lang,
                parse_method=parse_method,
                start_page_id=start_page_id,
                end_page_id=end_page_id,
                pipeline_version=pipeline_version,
            )

            return file.filename, resolved_lang, analysis_results
        except HTTPException:
            raise
        except Exception as e:
            logger.exception(
                f"[{pipeline_version}] Error during MinerU processing for file '{file.filename}': {e}"
            )
            raise HTTPException(
                status_code=500,
                detail=f"Internal server error in MinerU service ({pipeline_version}): {str(e)}",
            )
        finally:
            async with _active_tasks_lock:
                _active_tasks -= 1
            try:
                import shutil

                shutil.rmtree(temp_dir, ignore_errors=True)
            except Exception:
                pass


async def _run_analysis(
    *,
    file: UploadFile,
    lang: Optional[str],
    parse_method: str,
    start_page_id: int,
    end_page_id: Optional[int],
    pipeline_version: str,
):
    filename, resolved_lang, analysis_results = await _execute_analysis(
        file=file,
        lang=lang,
        parse_method=parse_method,
        start_page_id=start_page_id,
        end_page_id=end_page_id,
        pipeline_version=pipeline_version,
    )

    return Response(
        content=json.dumps(
            {
                "filename": filename,
                "pipeline_version": pipeline_version,
                "lang": resolved_lang,
                "preprocessing_mode": "custom",
                "preprocessing": {
                    "dpi": PDF_RENDER_DPI,
                    "max_side": MAX_RENDER_SIDE,
                    "image_to_pdf": "images_bytes_to_pdf_bytes_at_dpi",
                },
                "analysis_results": analysis_results,
            },
            ensure_ascii=False,
        ),
        media_type="application/json",
    )


async def _run_content_lines(
    *,
    file: UploadFile,
    lang: Optional[str],
    parse_method: str,
    start_page_id: int,
    end_page_id: Optional[int],
    pipeline_version: str,
    include_discarded: bool,
):
    filename, resolved_lang, analysis_results = await _execute_analysis(
        file=file,
        lang=lang,
        parse_method=parse_method,
        start_page_id=start_page_id,
        end_page_id=end_page_id,
        pipeline_version=pipeline_version,
    )

    items = build_content_lines(analysis_results, include_discarded=include_discarded)

    return Response(
        content=json.dumps(
            {
                "filename": filename,
                "pipeline_version": pipeline_version,
                "lang": resolved_lang,
                "item_count": len(items),
                "items": items,
            },
            ensure_ascii=False,
        ),
        media_type="application/json",
    )


CONTENT_LINES_NOTE = (
    "Returns a flat JSON array of content lines: each item has type, content, bbox, and page_idx. "
    "By default also includes text from discarded_blocks (headers/margins) so form fields like "
    "'Sex: F' are not lost. Set include_discarded=false to match content_list_json only."
)


@app.post(
    "/content_lines/v2",
    summary="Flat content lines — type, content, bbox (v2 pipeline)",
    description=f"{PIPELINE_V2_NOTE} {CONTENT_LINES_NOTE} {CONCURRENCY_NOTE}",
)
async def content_lines_v2(
    file: UploadFile = File(..., description=f"Supported types: {sorted(ALLOWED_EXTENSIONS)}"),
    lang: Optional[str] = Query(None, description=LANG_QUERY_DESCRIPTION),
    parse_method: str = Query("auto", description="Parsing method: 'auto', 'txt', or 'ocr'"),
    start_page_id: int = Query(0, description="Starting page (0-indexed). Applied before analysis."),
    end_page_id: Optional[int] = Query(None, description="Ending page (inclusive). None means last page."),
    include_discarded: bool = Query(
        True,
        description="Include text from discarded_blocks (headers, footers, margin fields).",
    ),
):
    return await _run_content_lines(
        file=file,
        lang=lang,
        parse_method=parse_method,
        start_page_id=start_page_id,
        end_page_id=end_page_id,
        pipeline_version="v2",
        include_discarded=include_discarded,
    )


@app.post(
    "/content_lines/v3",
    summary="Flat content lines — type, content, bbox (v3 pipeline)",
    description=f"{PIPELINE_V3_NOTE} {CONTENT_LINES_NOTE} {CONCURRENCY_NOTE}",
)
async def content_lines_v3(
    file: UploadFile = File(..., description=f"Supported types: {sorted(ALLOWED_EXTENSIONS)}"),
    lang: Optional[str] = Query(None, description=LANG_QUERY_DESCRIPTION),
    parse_method: str = Query("auto", description="Parsing method: 'auto', 'txt', or 'ocr'"),
    start_page_id: int = Query(0, description="Starting page (0-indexed). Applied before analysis."),
    end_page_id: Optional[int] = Query(None, description="Ending page (inclusive). None means last page."),
    include_discarded: bool = Query(
        True,
        description="Include text from discarded_blocks (headers, footers, margin fields).",
    ),
):
    return await _run_content_lines(
        file=file,
        lang=lang,
        parse_method=parse_method,
        start_page_id=start_page_id,
        end_page_id=end_page_id,
        pipeline_version="v3",
        include_discarded=include_discarded,
    )


@app.post(
    "/analyze_layout/v2",
    summary="Layout analysis — MinerU 2.0.6-style pipeline (batch doc_analyze)",
    description=f"{PIPELINE_V2_NOTE} {PREPROCESSING_NOTE} {CONCURRENCY_NOTE}",
)
async def analyze_document_v2(
    file: UploadFile = File(..., description=f"Supported types: {sorted(ALLOWED_EXTENSIONS)}"),
    lang: Optional[str] = Query(
        None,
        description=LANG_QUERY_DESCRIPTION,
    ),
    parse_method: str = Query("auto", description="Parsing method: 'auto', 'txt', or 'ocr'"),
    start_page_id: int = Query(0, description="Starting page (0-indexed). Applied before analysis."),
    end_page_id: Optional[int] = Query(None, description="Ending page (inclusive). None means last page."),
):
    return await _run_analysis(
        file=file,
        lang=lang,
        parse_method=parse_method,
        start_page_id=start_page_id,
        end_page_id=end_page_id,
        pipeline_version="v2",
    )


@app.post(
    "/analyze_layout/v3",
    summary="Layout analysis — MinerU 3.2.1 streaming pipeline (doc_analyze_streaming)",
    description=f"{PIPELINE_V3_NOTE} {PREPROCESSING_NOTE} {CONCURRENCY_NOTE}",
)
async def analyze_document_v3(
    file: UploadFile = File(..., description=f"Supported types: {sorted(ALLOWED_EXTENSIONS)}"),
    lang: Optional[str] = Query(
        None,
        description=LANG_QUERY_DESCRIPTION,
    ),
    parse_method: str = Query("auto", description="Parsing method: 'auto', 'txt', or 'ocr'"),
    start_page_id: int = Query(0, description="Starting page (0-indexed). Applied before analysis."),
    end_page_id: Optional[int] = Query(None, description="Ending page (inclusive). None means last page."),
):
    return await _run_analysis(
        file=file,
        lang=lang,
        parse_method=parse_method,
        start_page_id=start_page_id,
        end_page_id=end_page_id,
        pipeline_version="v3",
    )


@app.post(
    "/analyze_layout/",
    summary="Deprecated — use /analyze_layout/v2",
    description="Backward-compatible alias for /analyze_layout/v2.",
    deprecated=True,
)
async def analyze_document_legacy(
    file: UploadFile = File(...),
    lang: Optional[str] = Query(None, description=LANG_QUERY_DESCRIPTION),
    parse_method: str = Query("auto"),
    start_page_id: int = Query(0),
    end_page_id: Optional[int] = Query(None),
):
    return await _run_analysis(
        file=file,
        lang=lang,
        parse_method=parse_method,
        start_page_id=start_page_id,
        end_page_id=end_page_id,
        pipeline_version="v2",
    )


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8087)
