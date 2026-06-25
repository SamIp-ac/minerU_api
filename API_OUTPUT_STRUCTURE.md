# MinerU API Output JSON Structure

Endpoints:

- `POST /analyze_layout/v2`
- `POST /analyze_layout/v3`
- `POST /analyze_layout/` (deprecated alias of v2)
- `POST /content_lines/v2` — flat type/content/bbox lines only
- `POST /content_lines/v3` — flat type/content/bbox lines only

Both routes return the **same top-level JSON envelope**.  
Only `pipeline_version` and `analysis_results.pipeline` differ.  
Nested field values (`middle_json`, coordinates, markdown text) are **not guaranteed identical** between v2 and v3.

This API pins **`mineru[core]==3.2.1`** (see `requirements.txt`) but overrides MinerU’s default **200 DPI** render path with **400 DPI** in `input_utils.py`.

---

## Top-level response (v2 and v3)

| Field | Type | Description |
|-------|------|-------------|
| `filename` | `string` | Original uploaded filename |
| `pipeline_version` | `"v2"` \| `"v3"` | Which pipeline handled the request |
| `lang` | `string` \| `null` | Resolved OCR language hint (`null` = multilingual/default OCR path) |
| `preprocessing_mode` | `"custom"` | API overrides MinerU 3.2.1 default (200 DPI) |
| `preprocessing` | `object` | Effective render settings for this request (see below) |
| `analysis_results` | `object` | Parsed layout output (see below) |

### `preprocessing` object

| Field | Type | Description |
|-------|------|-------------|
| `dpi` | `integer` | PDF/image page render DPI. **400** (API override; MinerU default is 200) |
| `max_side` | `integer` | Long-side pixel cap passed to `page_to_image`. **3500** |
| `image_to_pdf` | `string` | Image upload path. **`images_bytes_to_pdf_bytes_at_dpi`** (EXIF transpose, RGB, PDF save at 400 DPI, quality=95) |

Applies to both v2 and v3:

| Step | Setting (this API) | MinerU 3.2.1 default |
|------|-------------------|----------------------|
| PDF render DPI | **400** | 200 |
| Long-side cap | **3500 px** | 3500 px |
| Image → PDF | **400 DPI save** | 200 DPI save |
| Image page render DPI | **400** | 200 |

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

## Flat content lines (`POST /content_lines/v2` and `/content_lines/v3`)

Lightweight response for keyword → bbox lookup. No full `middle_json` / `markdown`.

### Top-level response

| Field | Type | Description |
|-------|------|-------------|
| `filename` | `string` | Original uploaded filename |
| `pipeline_version` | `"v2"` \| `"v3"` | Pipeline used |
| `lang` | `string` \| `null` | OCR language hint |
| `item_count` | `integer` | Number of lines in `items` |
| `items` | `array` | Flat content lines (see below) |

Query parameter **`include_discarded`** (default `true`): append span text from `discarded_blocks` (headers, margins, footers).

### `items[]` (each line)

| Field | Type | Description |
|-------|------|-------------|
| `line_index` | `integer` | 0-based index in reading order |
| `type` | `string` | `text`, `title`, `image`, `table`, `equation`, `header`, `footer`, … |
| `content` | `string` \| `null` | Text, table HTML, image path, etc. |
| `bbox` | `[int,int,int,int]` \| `null` | Box coordinates (often 0–1000 normalized scale) |
| `page_idx` | `integer` | Source page, 0-based |
| `source` | `string` | Present when from `discarded_blocks` (`"discarded"`) |

### Example

```json
{
  "filename": "form.pdf",
  "pipeline_version": "v2",
  "lang": "en",
  "item_count": 3,
  "items": [
    {
      "line_index": 0,
      "type": "header",
      "content": "Sex: F",
      "bbox": [620, 45, 710, 62],
      "page_idx": 0,
      "source": "discarded"
    },
    {
      "line_index": 1,
      "type": "text",
      "content": "Chief complaint",
      "bbox": [85, 120, 320, 140],
      "page_idx": 0
    },
    {
      "line_index": 2,
      "type": "table",
      "content": "<table>...</table>",
      "bbox": [50, 200, 550, 400],
      "page_idx": 0
    }
  ]
}
```

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
  "preprocessing_mode": "custom",
  "preprocessing": {
    "dpi": 400,
    "max_side": 3500,
    "image_to_pdf": "images_bytes_to_pdf_bytes_at_dpi"
  },
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
          "width": 3400,
          "height": 4400
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
        "width": 3400,
        "height": 4400
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
  "preprocessing_mode": "custom",
  "preprocessing": {
    "dpi": 400,
    "max_side": 3500,
    "image_to_pdf": "images_bytes_to_pdf_bytes_at_dpi"
  },
  "analysis_results": {
    "middle_json": { "... same schema as v2; values may differ ..." },
    "model_json": [ "... same schema as v2; values may differ ..." ],
    "content_list_json": [ "... same schema as v2; values may differ ..." ],
    "markdown": "...",
    "pipeline": "v3_streaming",
    "rendered_pages": [
      {
        "page_index": 0,
        "width": 3400,
        "height": 4400
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
4. Use **`preprocessing`** and **`rendered_pages`** to verify render settings and output page size (long side should be ≤ `preprocessing.max_side`, typically 3500).
5. Compare v2 vs v3 on the same file by diffing `markdown` or `content_list_json`, not only `pipeline`.

---

## Reference

MinerU official middle.json / content_list docs:  
https://opendatalab.github.io/MinerU/reference/output_files/

Render settings are defined in this repo’s `input_utils.py` (`PDF_RENDER_DPI = 400`, `MAX_RENDER_SIDE = 3500`). MinerU 3.2.1 library defaults remain 200 DPI — see `mineru/utils/pdf_image_tools.py` and `mineru/utils/pdf_reader.py` on the `mineru-3.2.1-released` tag.
