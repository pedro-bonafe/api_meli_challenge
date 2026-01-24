FROM python:3.11-slim

WORKDIR /app

# deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# code
COPY code/ /app/code/

EXPOSE 8000

ENV STORAGE=csv
ENV DATA_ROOT=/app/data
ENV DATASET_MODE=original
ENV CACHE_MAX=256
ENV NGRAM_N=3
ENV MAX_CANDIDATES=2000

CMD ["uvicorn", "code.app:app", "--host", "0.0.0.0", "--port", "8000"]
