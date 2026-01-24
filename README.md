
# Name Matching API

## Descripción General

Esta API permite comparar un nombre completo ingresado por un usuario contra una base histórica de nombres, identificando posibles coincidencias y devolviendo un ranking ordenado por similitud.

El sistema fue diseñado desde el inicio para:

- Ser **explicable** (no una caja negra).
- Ser **robusto** frente a errores humanos frecuentes: acentos, títulos, símbolos, espacios duplicados.
- Tener **orden determinístico** y resultados reproducibles.
- Ser **eficiente**, incluso al escalar el volumen de datos.
- Poder **evolucionar progresivamente** hacia una arquitectura productiva.

---

## Análisis previo del dataset (Notebook)

Antes de construir la API se realizó un análisis exploratorio del dataset (`names_dataset.csv`) en un notebook (`dataset_analysis_names.ipynb`).

### Hallazgos principales

- Alta proporción de **nombres duplicados semánticamente**, con variaciones por:
  - Acentos (`Gómez` / `Gomez`)
  - Títulos (`Dr.`, `Lic.`, `Sra.`)
  - Símbolos y ruido (`!!`, `@`, espacios múltiples)
- Repetición de la misma persona con diferencias puramente tipográficas.
- Imposibilidad de separar nombre y apellido de forma confiable (nombres compuestos, apellidos múltiples).

### Decisiones tomadas

1. **Trabajar siempre con el nombre completo**, no intentar separar nombre/apellido.
2. Definir una **normalización estricta y determinista** (`normalize_strict`).
3. Construir tres modos de dataset:
   - `original`
   - `standardized`
   - `standardized+dedupe`
4. Medir impacto real en:
   - Calidad del ranking
   - Cantidad de candidatos
   - Latencia

Los benchmarks mostraron que **`standardized+dedupe` reduce significativamente el tiempo de búsqueda** manteniendo o mejorando la calidad del ranking.

---

## Normalización estricta

La normalización aplicada (tanto al dataset como al input del cliente) sigue estas reglas:

- Minúsculas
- Eliminación de acentos
- Eliminación de títulos (`Dr.`, `Lic.`, etc.)
- Eliminación de símbolos y puntuación
- Colapso de espacios múltiples

Ejemplo:

```

"Dr. Ana   Álvarez Fernández!!"
→ "ana alvarez fernandez"

```

Esto garantiza que:
- La comparación sea justa.
- El matching no dependa de ruido humano.
- El comportamiento sea reproducible.

---

## Estructura del proyecto

```

/code
├── app.py
├── matching.py
├── search_engine.py
├── storage.py
└── metrics.py

/data
├── raw
│   └── names_dataset.csv
└── clean
└── names_dataset_standardized.csv

````

---

## Cómo ejecutar la API

### Requisitos

- Docker
- Docker Compose
- No es necesario tener Python instalado localmente

---

## Modos de ejecución (usando `.env`)

La API soporta **múltiples modos de dataset**, configurables sin cambiar código.

### Archivos `.env`

#### `.env.original`
```env
STORAGE=sqlite
DATASET_MODE=original
SQLITE_FORCE_RELOAD=true
````

#### `.env.standardized`

```env
STORAGE=sqlite
DATASET_MODE=standardized
SQLITE_FORCE_RELOAD=true
```

#### `.env.standardized_dedupe`

```env
STORAGE=sqlite
DATASET_MODE=standardized+dedupe
SQLITE_FORCE_RELOAD=true
```

### Ejecutar un modo específico

```bash
docker compose --env-file .env.standardized_dedupe up --build api_sqlite
```

### Ejecución modo deffault (standardized_dedupe)

**Ejecución con csv:**

```bash
docker compose up --build api_csv

```

**Ejecución con SQLite:**

```bash
docker compose up --build api_sqlite

```


### Endpoints disponibles

La API quedará disponible en:

* **API Root:** 
  * `api_csv` → http://localhost:8000
  * `api_sqlite` → http://localhost:8001
* **Swagger (documentación interactiva):** 
  * `api_csv` → http://localhost:8000/docs
  * `api_sqlite` → http://localhost:8001/docs
---

## Endpoints

### POST `/match`

Endpoint principal de matching.

#### Request

```json
{
  "name": "ana gz muniz",
  "threshold": 70,
  "limit": 10,
  "w_token": 0.65,
  "explain": false,
  "include_by_id": true
}
```

#### Parámetros

| Campo           | Descripción                               |
| --------------- | ----------------------------------------- |
| `name`          | Nombre a buscar (input libre del usuario) |
| `threshold`     | Similaridad mínima (0–100)                |
| `limit`         | Máximo de resultados                      |
| `w_token`       | Peso de similitud por tokens              |
| `explain`       | Devuelve scores intermedios               |
| `include_by_id` | Mapa auxiliar por ID                      |

#### Response

```json
{
  "results": [
    {
      "id": 189,
      "name": "Ana Gómez Ruiz",
      "similarity": 76.92
    }
  ],
  "results_by_id": {
    "189": {
      "name": "Ana Gómez Ruiz",
      "similarity": 76.92
    }
  }
}
```

> **Nota:**
> * El orden no se confía a objetos JSON, sino a listas (decisión de diseño).
> * `results` es una **lista ordenada** acorde a los requerimientos (ranking garantizado).
> * `results_by_id` es solo un acceso auxiliar.

---

### GET `/metrics`

Devuelve métricas internas del sistema.

Incluye:

* Requests totales
* Cache hit rate
* Latencia promedio y p95
* Cantidad de candidatos evaluados
* Estadísticas de resolución de empates
* Configuración activa del repositorio

Ejemplo:

```json
{
  "cache_hit_rate": 0.42,
  "latency_ms_avg": 5.4,
  "tie_break": {
    "resolved_by_token_pct": 0.62,
    "resolved_by_edit_pct": 0.28,
    "resolved_by_id_pct": 0.10
  },
  "repo": {
    "storage": "sqlite",
    "dataset_mode": "standardized+dedupe"
  }
}
```

---

## Arquitectura de Matching

### Flujo general

1. Normalización estricta del input.
2. Generación de candidatos mediante índice de n-grams.
3. Cálculo de similitud:

   * `token_set_ratio`
   * `ratio` (edición)
4. Score ponderado (0–100).
5. Orden determinístico:

   1. `similarity`
   2. `token_score`
   3. `edit_score`
   4. `id`
6. Cache LRU para consultas repetidas.

---

## Persistencia: CSV vs SQLite

### CSV (modo simple)

* Dataset cargado en memoria.
* Ideal para pruebas rápidas.

### SQLite (modo recomendado)

* Persistencia embebida.
* Permite deduplicación real.
* Transición directa a PostgreSQL/MySQL sin cambiar la API.
* Archivo `.db` persistido mediante volumen Docker.

---

## Escalabilidad

El diseño permite escalar progresivamente:

* Reemplazar SQLite por PostgreSQL.
* Desacoplar el índice de búsqueda.
* Paralelizar scoring.
* Incorporar motores como Elasticsearch o vector DBs.
* Integrar embeddings o re-ranking por IA si el dominio lo requiere.


## Conclusión

Esta API prioriza **calidad de datos**, **explicabilidad**, **orden determinístico** y **buen diseño de ingeniería**.
El objetivo fue brindar solución simple, robusta y escalable, que se adapte a las arquitecturas propuestas en el documento.


