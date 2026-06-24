# # mineru_service.py
# import os
# import io
# import json
# import tempfile
# from pathlib import Path
# from typing import Optional

# # --- FastAPI and other Imports ---
# import uvicorn
# from fastapi import FastAPI, UploadFile, File, HTTPException, Query, Response
# from loguru import logger

# # --- MinerU Imports: aligned with MinerU 3.2.x CLI pipeline flow ---
# import copy

# from mineru.cli.common import convert_pdf_bytes_to_bytes, prepare_env, read_fn
# from mineru.data.data_reader_writer import FileBasedDataWriter
# from mineru.utils.enum_class import MakeMode
# from mineru.backend.pipeline.pipeline_analyze import doc_analyze_streaming
# from mineru.backend.pipeline.pipeline_middle_json_mkcontent import union_make as pipeline_union_make


# # --- FastAPI App Definition ---
# app = FastAPI(
#     title="MinerU Document Analysis Service (Strictly following main.py logic)",
#     description="A service dedicated to running the AGPL-licensed MinerU library, strictly adhering to the file processing logic of the original main.py script.",
#     version="1.3.0",
# )

# # Define the set of allowed file extensions from main.py
# ALLOWED_EXTENSIONS = {".pdf", ".png", ".jpeg", ".jpg"}


# def do_parse_in_api(
#     output_dir: str,
#     pdf_file_names: list[str],
#     pdf_bytes_list: list[bytes],
#     p_lang_list: list[str],
#     parse_method: str,
#     start_page_id: int,
#     end_page_id: Optional[int],
#     p_formula_enable: bool = True,
#     p_table_enable: bool = True,
#     f_make_md_mode: MakeMode = MakeMode.MM_MD,
# ):
#     """
#     Run the MinerU 3.2.x pipeline backend and return parsed data instead of writing files.
#     """
#     prepared_bytes_list = [
#         convert_pdf_bytes_to_bytes(pdf_bytes, start_page_id, end_page_id)
#         for pdf_bytes in pdf_bytes_list
#     ]

#     image_writer_list: list[FileBasedDataWriter] = []
#     local_image_dirs: list[str] = []
#     for pdf_file_name in pdf_file_names:
#         local_image_dir, _local_md_dir = prepare_env(output_dir, pdf_file_name, parse_method)
#         local_image_dirs.append(local_image_dir)
#         image_writer_list.append(FileBasedDataWriter(local_image_dir))

#     results: dict[int, dict] = {}

#     def on_doc_ready(doc_index: int, model_list, middle_json, _ocr_enable: bool) -> None:
#         pdf_file_name = pdf_file_names[doc_index]
#         pdf_info = middle_json["pdf_info"]
#         image_dir = str(os.path.basename(local_image_dirs[doc_index]))
#         md_content_str = pipeline_union_make(pdf_info, f_make_md_mode, image_dir)
#         content_list = pipeline_union_make(pdf_info, MakeMode.CONTENT_LIST, image_dir)
#     # --- End: Code directly from main.py's do_parse ---

#         logger.info(f"MinerU analysis complete for {pdf_file_name}")
#         results[doc_index] = {
#             "middle_json": middle_json,
#             "model_json": copy.deepcopy(model_list),
#             "content_list_json": content_list,
#             "markdown": md_content_str,
#         }

#     doc_analyze_streaming(
#         prepared_bytes_list,
#         image_writer_list,
#         p_lang_list,
#         on_doc_ready,
#         parse_method=parse_method,
#         formula_enable=p_formula_enable,
#         table_enable=p_table_enable,
#     )

#     if not results:
#         raise RuntimeError("MinerU analysis failed to produce any output.")

#     return results[min(results.keys())]


# @app.post("/analyze_layout/", summary="Analyze document layout following main.py logic")
# async def analyze_document(
#     file: UploadFile = File(..., description=f"The document to analyze. Supported types: {list(ALLOWED_EXTENSIONS)}"),
#     lang: str = Query("en", description="Document language ('ch', 'en', 'korean', 'japan', etc.)"),
#     parse_method: str = Query("auto", description="Parsing method: 'auto', 'txt', or 'ocr'"),
#     start_page_id: int = Query(0, description="The starting page for analysis (0-indexed)."),
#     end_page_id: Optional[int] = Query(None, description="The ending page for analysis. 'None' means to the end.")
# ):
#     """
#     Accepts a document (PDF or Image) and returns its detailed layout analysis as JSON.
#     This endpoint strictly follows the processing pipeline defined in the refersence `main.py` script.
#     """
#     file_extension = Path(file.filename).suffix.lower()
#     if file_extension not in ALLOWED_EXTENSIONS:
#         raise HTTPException(
#             status_code=400,
#             detail=f"File type '{file_extension}' not supported. Please upload one of: {list(ALLOWED_EXTENSIONS)}"
#         )

#     with tempfile.TemporaryDirectory() as temp_dir:
#         # `read_fn` requires a file path, so we must save the uploaded file temporarily.
#         temp_file_path = os.path.join(temp_dir, file.filename)
#         with open(temp_file_path, "wb") as f:
#             content = await file.read()
#             f.write(content)

#         try:
#             # --- Start: Code directly from main.py's parse_doc ---
#             # Use 'read_fn' exactly as in the original code. This function handles
#             # both PDF and image inputs correctly, returning PDF-formatted bytes.
#             logger.info(f"Processing '{temp_file_path}' using read_fn...")
#             pdf_bytes = read_fn(temp_file_path)
            
#             file_name_list = [Path(file.filename).stem]
#             pdf_bytes_list = [pdf_bytes]
#             lang_list = [lang]

#             # Call the core processing function, which is a direct copy of do_parse
#             analysis_results = do_parse_in_api(
#                 output_dir=temp_dir,
#                 pdf_file_names=file_name_list,
#                 pdf_bytes_list=pdf_bytes_list,
#                 p_lang_list=lang_list,
#                 parse_method=parse_method,
#                 start_page_id=start_page_id,
#                 end_page_id=end_page_id
#             )
#             # --- End: Code directly from main.py's parse_doc ---

#             # Return the collected results in a single JSON response
#             return Response(
#                 content=json.dumps({
#                     "filename": file.filename,
#                     "analysis_results": analysis_results
#                 }, ensure_ascii=False),
#                 media_type="application/json"
#             )
            
#         except Exception as e:
#             logger.exception(f"An error occurred during MinerU processing for file '{file.filename}': {e}")
#             raise HTTPException(status_code=500, detail=f"Internal server error in MinerU service: {str(e)}")


# if __name__ == "__main__":
#     uvicorn.run(app, host="0.0.0.0", port=8087)