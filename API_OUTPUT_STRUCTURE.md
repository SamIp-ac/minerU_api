# MinerU API Output JSON Structure

Endpoints:

- `POST /analyze_layout/v2`
- `POST /analyze_layout/v3`
- `POST /analyze_layout/` (deprecated alias of v2)

Both routes return the **same top-level JSON envelope**.  
Only `pipeline_version` and `analysis_results.pipeline` differ.  
Nested field values (`middle_json`, coordinates, markdown text) are **not guaranteed identical** between v2 and v3.

---

## Top-level response (v2 and v3)

| Field | Type | Description |
|-------|------|-------------|
| `filename` | `string` | Original uploaded filename |
| `pipeline_version` | `"v2"` \| `"v3"` | Which pipeline handled the request |
| `lang` | `string` \| `null` | Resolved OCR language hint (`null` = multilingual/default OCR path) |
| `native_resolution_mode` | `boolean` | Always `true` in current API (no 200 DPI / 3500px downscale in our layer) |
| `analysis_results` | `object` | Parsed layout output (see below) |

---

## `analysis_results` object (v2 and v3)

| Field | Type | Description |
|-------|------|-------------|
| `middle_json` | `object` | MinerU intermediate layout JSON |
| `model_json` | `array` | Raw per-page model output before full middle_json assembly |
| `content_list_json` | `array` | Flat content list in reading order |
| `markdown` | `string` | Multi-modal Markdown (`MM_MD` mode) |
| `pipeline` | `string` | `"v2_legacy_doc_analyze"` or `"v3_streaming"` |
| `rendered_pages` | `array` | Pixel size of each rendered page sent to inference |

### v2 vs v3 — only these differ at this level

| Field | v2 | v3 |
|-------|----|----|
| `pipeline` | `"v2_legacy_doc_analyze"` | `"v3_streaming"` |
| Internal generation | `doc_analyze` → `result_to_middle_json` | `doc_analyze_streaming` → incremental middle_json |

All other keys use the **same names and types**.

---

## `rendered_pages[]`

| Field | Type | Description |
|-------|------|-------------|
| `page_index` | `integer` | 0-based page index |
| `width` | `integer` | Rendered image width in pixels |
| `height` | `integer` | Rendered image height in pixels |

---

## `middle_json`

| Field | Type | Description |
|-------|------|-------------|
| `pdf_info` | `array` | One entry per page |
| `_backend` | `string` | `"pipeline"` for this API |
| `_version_name` | `string` | MinerU library version (e.g. `"3.2.1"`) |

### `middle_json.pdf_info[]` (per page)

| Field | Type | Description |
|-------|------|-------------|
| `page_idx` | `integer` | Page number, 0-based |
| `page_size` | `[number, number]` | Page size `[width, height]` in PDF units |
| `preproc_blocks` | `array` | Layout blocks before paragraph merge |
| `para_blocks` | `array` | Blocks after paragraph segmentation (v3 finalize; v2 may vary) |
| `discarded_blocks` | `array` | Headers, footers, page numbers, etc. |
| `images` | `array` | Image block metadata |
| `tables` | `array` | Table block metadata |
| `interline_equations` | `array` | Display formula blocks |

### Block hierarchy (inside `preproc_blocks` / `para_blocks`)

```text
block
├── type          string   e.g. text, title, image, table, interline_equation
├── bbox          [x0,y0,x1,y1]
├── level         integer  (title levels, optional)
├── lines[]       line
│   ├── bbox
│   └── spans[]
│       ├── bbox
│       ├── content   string
│       ├── type      string
│       └── score     number (OCR confidence, optional)
└── blocks[]      nested sub-blocks (tables/images)
```

---

## `model_json`

`array` of per-page raw detection results.

Each item:

| Field | Type | Description |
|-------|------|-------------|
| `layout_dets` | `array` | Raw layout detection boxes from inference |
| `page_info` | `object` | `{ "page_no": int, "width": int, "height": int }` |

Each `layout_dets[]` item typically includes category/label, score, and polygon or bbox coordinates (MinerU internal format).

---

## `content_list_json`

Flat `array` in **reading order**. Each element is one content item.

Common fields:

| Field | Type | Description |
|-------|------|-------------|
| `type` | `string` | `text`, `title`, `image`, `table`, `equation`, `code`, `list`, … |
| `text` | `string` | Text content (when applicable) |
| `text_level` | `integer` | Heading level; absent or `0` = body text |
| `page_idx` | `integer` | Source page, 0-based |
| `bbox` | `[int,int,int,int]` | Box coordinates (often 0–1000 normalized scale) |
| `img_path` | `string` | Relative path to cropped image/table asset (optional) |

Other fields may appear depending on `type` (`table_body`, `code_body`, `sub_type`, etc.).

---

## `markdown`

`string` — full document as Markdown with embedded image references, tables as HTML, and formulas as LaTeX where detected.

---

## Example — v2 response

```json
{
  "filename": "document.pdf",
  "pipeline_version": "v2",
  "lang": null,
  "native_resolution_mode": true,
  "analysis_results": {
    "middle_json": {
      "pdf_info": [
        {
          "page_idx": 0,
          "page_size": [612.0, 792.0],
          "preproc_blocks": [
            {
              "type": "text",
              "bbox": [52, 62, 294, 83],
              "lines": [
                {
                  "bbox": [52, 62, 294, 72],
                  "spans": [
                    {
                      "bbox": [54, 62, 296, 72],
                      "content": "Sample line of text",
                      "type": "text",
                      "score": 0.98
                    }
                  ]
                }
              ]
            }
          ],
          "para_blocks": [],
          "discarded_blocks": [],
          "images": [],
          "tables": [],
          "interline_equations": []
        }
      ],
      "_backend": "pipeline",
      "_version_name": "3.2.1"
    },
    "model_json": [
      {
        "layout_dets": [
          {
            "category_id": 1,
            "poly": [52, 62, 294, 62, 294, 83, 52, 83],
            "score": 0.95
          }
        ],
        "page_info": {
          "page_no": 0,
          "width": 2550,
          "height": 3300
        }
      }
    ],
    "content_list_json": [
      {
        "type": "text",
        "text": "Sample line of text",
        "page_idx": 0,
        "bbox": [85, 78, 480, 104]
      }
    ],
    "markdown": "# Sample line of text\n",
    "pipeline": "v2_legacy_doc_analyze",
    "rendered_pages": [
      {
        "page_index": 0,
        "width": 2550,
        "height": 3300
      }
    ]
  }
}
```

---

## Example — v3 response

Same envelope and `analysis_results` keys. Only identifiers change:

```json
{
  "filename": "document.pdf",
  "pipeline_version": "v3",
  "lang": null,
  "native_resolution_mode": true,
  "analysis_results": {
    "middle_json": { "... same schema as v2; values may differ ..." },
    "model_json": [ "... same schema as v2; values may differ ..." ],
    "content_list_json": [ "... same schema as v2; values may differ ..." ],
    "markdown": "...",
    "pipeline": "v3_streaming",
    "rendered_pages": [
      {
        "page_index": 0,
        "width": 2550,
        "height": 3300
      }
    ]
  }
}
```

---

## Error response (HTTP 4xx / 5xx)

FastAPI error format:

```json
{
  "detail": "Internal server error in MinerU service (v2): <message>"
}
```

Common `detail` cases:

| HTTP | Example `detail` |
|------|------------------|
| 400 | `File type '.docx' not supported. Please upload one of: ...` |
| 500 | MinerU inference / processing exception message |

---

## Notes for downstream integration

1. Prefer **`content_list_json`** for structured per-block consumption.
2. Prefer **`markdown`** for human-readable or LLM text input.
3. Prefer **`middle_json`** when you need full layout tree, spans, and coordinates.
4. Use **`rendered_pages`** to verify input resolution after native-resolution loading.
5. Compare v2 vs v3 on the same file by diffing `markdown` or `content_list_json`, not only `pipeline`.

---

## Reference

MinerU official middle.json / content_list docs:  
https://opendatalab.github.io/MinerU/reference/output_files/
