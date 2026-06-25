# Docker Start

```shell
docker build -f dockerfile -t samipdocker/mineru-api:latest .

docker push samipdocker/mineru-api:latest

docker run -d \
  --name mineru-container \
  -p 8087:8087 \
  -v mineru_models:/app/.cache \
  -e MINERU_MAX_CONCURRENT_TASKS=2 \
  --restart unless-stopped \
  samipdocker/mineru-api:latest
```

## Note
Using for ui demo
## streamlit demo
```shell
streamlit run app.py
```

## TODO

```markdown
要用 keyword 反查 bbox + 類型（table/text 等） → 優先用 analysis_results.content_list_json
要更細的 span 級座標或表格嵌套結構 → 用 middle_json.pdf_info
```