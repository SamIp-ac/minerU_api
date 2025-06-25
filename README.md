conda create -n gOCRapi_py310 python=3.10
conda activate gOCRapi_py310

Terminal 1: Start the MinerU Service
Make sure you have installed its specific dependencies: pip install "fastapi[all]" "mineru[all]" loguru pillow
Run the server. It will listen on port 8001.
uvicorn mineru_service:app --host 0.0.0.0 --port 8001
Terminal 2: Start the Main App Service
Make sure you have installed its dependencies: pip install "fastapi[all]" opencv-python-headless pillow requests loguru numpy (Note: opencv-python-headless is good for servers).
Run the server. It will listen on port 8000.
uvicorn main_app_service:app --host 0.0.0.0 --port 8002
Interact with Your Application
Open your browser to http://127.0.0.1:8000/docs.
Use the /process_document/ endpoint. You will see that it now asks for the mineru_service_url, which defaults to the correct address of our other service.

docker run -d --name mineru-container -p 8087:8087 -v mineru_models:/app/.cache samipdocker/mineru-api:latest