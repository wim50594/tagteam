FROM python:3.11-slim

WORKDIR /app

RUN pip install --no-cache-dir \
    fastapi==0.111.0 \
    uvicorn[standard]==0.29.0 \
    redis==5.0.4 \
    aiofiles==23.2.1 \
    pandas==2.2.2 \
    openpyxl==3.1.2 \
    python-multipart==0.0.9 \
    pydantic==2.7.1

COPY main.py .

RUN mkdir -p /app/data/media

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
