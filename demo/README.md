# MinerU v3 Streamlit demo (local only — this folder is gitignored)

## Setup

```bash
cd demo
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Ensure MinerU API is running, e.g.:

```bash
docker compose up -d
# API: http://localhost:8087
```

## Run

```bash
streamlit run app.py
```

Open the URL shown in the terminal (default `http://localhost:8501`).

## Usage

1. Set API base URL in the sidebar (default `http://localhost:8087`).
2. Upload PDF / PNG / JPG.
3. Click **Run `/analyze_layout/v3`**.
4. View **BBox overlay** tab — colored rectangles from `content_list_json`.
5. View **Raw JSON** tab for the full API response.
