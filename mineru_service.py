# mineru_service.py
import os
import io
import json
import tempfile
from pathlib import Path
from typing import Optional

# --- FastAPI and other Imports ---
import uvicorn
from fastapi import FastAPI, UploadFile, File, HTTPException, Query, Response
from loguru import logger

# --- MinerU Imports: This section strictly follows the provided main.py ---
import copy

# CRITICAL FIX: Import 'read_fn' exactly as in main.py. This is the key.
from mineru.cli.common import convert_pdf_bytes_to_bytes_by_pypdfium2, prepare_env, read_fn
from mineru.data.data_reader_writer import FileBasedDataWriter
from mineru.utils.enum_class import MakeMode
from mineru.backend.pipeline.pipeline_analyze import doc_analyze as pipeline_doc_analyze
from mineru.backend.pipeline.pipeline_middle_json_mkcontent import union_make as pipeline_union_make
from mineru.backend.pipeline.model_json_to_middle_json import result_to_middle_json as pipeline_result_to_middle_json


# --- FastAPI App Definition ---
app = FastAPI(
    title="MinerU Document Analysis Service (Strictly following main.py logic)",
    description="A service dedicated to running the AGPL-licensed MinerU library, strictly adhering to the file processing logic of the original main.py script.",
    version="1.3.0",
)

# Define the set of allowed file extensions from main.py
ALLOWED_EXTENSIONS = {".pdf", ".png", ".jpeg", ".jpg"}


def do_parse_in_api(
    output_dir: str,
    pdf_file_names: list[str],
    pdf_bytes_list: list[bytes],
    p_lang_list: list[str],
    parse_method: str,
    start_page_id: int,
    end_page_id: Optional[int],
    p_formula_enable: bool = True,
    p_table_enable: bool = True,
    f_make_md_mode: MakeMode = MakeMode.MM_MD,
):
    """
    This function is a direct adaptation of `do_parse` from main.py,
    modified to return data instead of writing all files.
    """
    # --- Start: Code directly from main.py's do_parse ---
    for idx, pdf_bytes in enumerate(pdf_bytes_list):
        new_pdf_bytes = convert_pdf_bytes_to_bytes_by_pypdfium2(pdf_bytes, start_page_id, end_page_id)
        pdf_bytes_list[idx] = new_pdf_bytes

    infer_results, all_image_lists, all_pdf_docs, lang_list, ocr_enabled_list = pipeline_doc_analyze(
        pdf_bytes_list, p_lang_list, parse_method=parse_method, formula_enable=p_formula_enable, table_enable=p_table_enable
    )

    # This loop will run once in the API context
    for idx, model_list in enumerate(infer_results):
        model_json = copy.deepcopy(model_list)
        pdf_file_name = pdf_file_names[idx]
        local_image_dir, local_md_dir = prepare_env(output_dir, pdf_file_name, parse_method)
        image_writer = FileBasedDataWriter(local_image_dir)

        images_list = all_image_lists[idx]
        pdf_doc = all_pdf_docs[idx]
        _lang = lang_list[idx]
        _ocr_enable = ocr_enabled_list[idx]

        middle_json = pipeline_result_to_middle_json(model_list, images_list, pdf_doc, image_writer, _lang, _ocr_enable, p_formula_enable)
        pdf_info = middle_json["pdf_info"]
        
        image_dir = str(os.path.basename(local_image_dir))
        md_content_str = pipeline_union_make(pdf_info, f_make_md_mode, image_dir)
        content_list = pipeline_union_make(pdf_info, MakeMode.CONTENT_LIST, image_dir)
    # --- End: Code directly from main.py's do_parse ---

        logger.info(f"MinerU analysis complete for {pdf_file_name}")
        
        # Return the data required by the API
        return {
            "middle_json": middle_json,
            "model_json": model_json,
            "content_list_json": content_list,
            "markdown": md_content_str
        }

    raise RuntimeError("MinerU analysis failed to produce any output.")


@app.post("/analyze_layout/", summary="Analyze document layout following main.py logic")
async def analyze_document(
    file: UploadFile = File(..., description=f"The document to analyze. Supported types: {list(ALLOWED_EXTENSIONS)}"),
    lang: str = Query("en", description="Document language ('ch', 'en', 'korean', 'japan', etc.)"),
    parse_method: str = Query("auto", description="Parsing method: 'auto', 'txt', or 'ocr'"),
    start_page_id: int = Query(0, description="The starting page for analysis (0-indexed)."),
    end_page_id: Optional[int] = Query(None, description="The ending page for analysis. 'None' means to the end.")
):
    """
    Accepts a document (PDF or Image) and returns its detailed layout analysis as JSON.
    This endpoint strictly follows the processing pipeline defined in the reference `main.py` script.
    """
    file_extension = Path(file.filename).suffix.lower()
    if file_extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"File type '{file_extension}' not supported. Please upload one of: {list(ALLOWED_EXTENSIONS)}"
        )

    with tempfile.TemporaryDirectory() as temp_dir:
        # `read_fn` requires a file path, so we must save the uploaded file temporarily.
        temp_file_path = os.path.join(temp_dir, file.filename)
        with open(temp_file_path, "wb") as f:
            content = await file.read()
            f.write(content)

        try:
            # --- Start: Code directly from main.py's parse_doc ---
            # Use 'read_fn' exactly as in the original code. This function handles
            # both PDF and image inputs correctly, returning PDF-formatted bytes.
            logger.info(f"Processing '{temp_file_path}' using read_fn...")
            pdf_bytes = read_fn(temp_file_path)
            
            file_name_list = [Path(file.filename).stem]
            pdf_bytes_list = [pdf_bytes]
            lang_list = [lang]

            # Call the core processing function, which is a direct copy of do_parse
            analysis_results = do_parse_in_api(
                output_dir=temp_dir,
                pdf_file_names=file_name_list,
                pdf_bytes_list=pdf_bytes_list,
                p_lang_list=lang_list,
                parse_method=parse_method,
                start_page_id=start_page_id,
                end_page_id=end_page_id
            )
            # --- End: Code directly from main.py's parse_doc ---

            # Return the collected results in a single JSON response
            return Response(
                content=json.dumps({
                    "filename": file.filename,
                    "analysis_results": analysis_results
                }, ensure_ascii=False),
                media_type="application/json"
            )
            
        except Exception as e:
            logger.exception(f"An error occurred during MinerU processing for file '{file.filename}': {e}")
            raise HTTPException(status_code=500, detail=f"Internal server error in MinerU service: {str(e)}")


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8087)