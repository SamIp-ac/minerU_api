# Docker

```shell
docker build -t samipdocker/mineru-api:latest .
docker run -d --name mineru-container -p 8087:8087 -v mineru_models:/app/.cache samipdocker/mineru-api:latest
```
