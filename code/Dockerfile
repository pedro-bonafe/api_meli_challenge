FROM python:3.11-slim

WORKDIR /app

# deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# code + dataset
COPY . .

# uvicorn port
EXPOSE 8000

# default envs (podés sobrescribir en compose)
ENV STORAGE=csv
ENV CSV_PATH=names_dataset.csv
ENV CACHE_MAX=256
ENV NGRAM_N=3
ENV MAX_CANDIDATES=2000

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
