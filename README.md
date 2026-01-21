# Name Matching API

##  Descripción General

Esta API permite comparar un nombre completo ingresado por un usuario contra una base de datos histórica de nombres, identificando posibles coincidencias y devolviendo un ranking ordenado por similitud.

El sistema fue diseñado para:
* Ser **explicable** (no una “caja negra”).
* Ser **robusto** ante errores tipográficos, acentos y variaciones de orden.
* Ser **eficiente** para escalar a datasets más grandes.
* Ser fácilmente **extensible** a un entorno productivo.

---

## 🚀 Cómo ejecutar la API

### Requisitos
* **Docker** + **Docker Compose**
* *(No es necesario tener Python instalado localmente)*

### Ejecución con base CSV (modo simple)
Desde la carpeta `code/`:

```bash
docker compose up --build api_csv

```

La API quedará disponible en:

* **API Root:** http://localhost:8000
* **Swagger (documentación interactiva):** http://localhost:8000/docs

---

## 📡 Endpoints Disponibles

### 1. POST `/match`

Endpoint principal de matching.

**Entrada (JSON):**

```json
{
  "name": "Pedro Vélez",
  "threshold": 70,
  "limit": 10,
  "w_token": 0.65,
  "explain": false,
  "include_by_id": true
}

```

**Parámetros:**

| Campo | Descripción |
| --- | --- |
| `name` | Nombre completo a buscar. |
| `threshold` | Umbral mínimo de similitud (0–100). |
| `limit` | Máximo de resultados a devolver. |
| `w_token` | Peso del componente de similitud por tokens. |
| `explain` | Si es `true`, devuelve detalle del score. |
| `include_by_id` | Si es `true`, agrega un mapa por ID. |

**Salida (JSON):**

```json
{
  "results": [
    {
      "id": 1791,
      "name": "Pedro López",
      "similarity": 81.82
    },
    {
      "id": 232,
      "name": "Pedro Jiménez",
      "similarity": 75.0
    }
  ],
  "results_by_id": {
    "1791": {
      "name": "Pedro López",
      "similarity": 81.82
    },
    "232": {
      "name": "Pedro Jiménez",
      "similarity": 75.0
    }
  }
}

```

> **Notas importantes:**
> * `results` es una lista ordenada de mayor a menor similitud.
> * `results_by_id` es opcional y permite acceso directo por ID.
> * El orden no se confía a objetos JSON, sino a listas (decisión de diseño).
> 
> 

### 2. GET `/match`

Misma funcionalidad que POST, pero usando query params (útil para testing manual).

**Ejemplo:**

```http
GET /match?name=Pedro%20Vélez&threshold=70&limit=10

```

### 3. GET `/metrics`

Devuelve métricas internas de la API.

**Salida (JSON):**

```json
{
  "total_requests": 120,
  "cache_hit_rate": 0.32,
  "latency_ms_avg": 14.2,
  "candidates_avg": 340,
  "tie_break": {
    "tie_groups_total": 18,
    "resolved_by_token_pct": 0.67,
    "resolved_by_edit_pct": 0.22,
    "resolved_by_id_pct": 0.11
  }
}

```

Incluye:

* Latencia promedio y p95.
* Uso del cache.
* Tamaño promedio de candidatos.
* Cómo se resolvieron empates de similitud.

---

## 🏗 Arquitectura y construcción

### Flujo general

1. **Normalización del texto:** Minúsculas, eliminación de acentos, colapso de espacios.
2. **Generación de candidatos:** Índice invertido por n-grams de caracteres (evita comparar contra todo el dataset).
3. **Cálculo de similitud:** Combinación ponderada de:
* Similitud por tokens (`token_set_ratio`).
* Distancia de edición (`ratio`).
* Score final en rango 0–100.


4. **Orden determinístico:**
1. `similarity` (sin redondear).
2. `token_score`.
3. `edit_score`.
4. `id` (desempate final estable).


5. **Cache LRU:** Acelera consultas repetidas.

### Decisiones técnicas clave

#### ¿Por qué no separar nombre y apellido?

El dataset no garantiza estructura semántica confiable (nombres compuestos, apellidos múltiples). Separar introduce heurísticas frágiles y empeora el ranking. **Se optó por trabajar sobre el nombre completo normalizado.**

#### ¿Por qué Levenshtein + token similarity?

* Funciona muy bien para nombres propios.
* Es explicable.
* No requiere entrenamiento.
* Es rápido y determinista.
* Evita dependencia de modelos externos.

#### ¿Por qué devolver resultados como lista?

Los objetos JSON no garantizan orden. El enunciado requiere resultados ordenados, por lo que el ranking se devuelve como lista ordenada, y el mapa por ID se incluye solo como complemento.

### Persistencia: CSV vs SQLite

**`api_csv` (Modo simple)**

* Dataset cargado desde CSV en memoria.
* Ideal para el challenge y datasets pequeños.

**`api_sqlite` (Modo persistente)**

* Usa SQLite como base embebida.
* Permite persistencia, queries reproducibles y transición suave a producción.
* SQLite corre embebido dentro del contenedor, persistiendo el archivo `.db` mediante un volumen Docker.

**Ejecución con SQLite:**

```bash
docker compose up --build api_sqlite

```

---

## 📈 Escalabilidad a producción

El diseño permite escalar sin reescribir la API. La separación clara entre **API**, **storage** y **search engine** permite evolucionar cada capa de forma independiente:

* Reemplazar SQLite por **PostgreSQL / MySQL**.
* Mover *candidate generation* a tablas indexadas.
* Agregar índices fonéticos.
* Paralelizar scoring.
* Incorporar embeddings si el dominio lo requiere.

---

## ✅ Conclusión

Esta API fue diseñada priorizando **precisión**, **explicabilidad**, **rendimiento** y **buenas prácticas de ingeniería**. El resultado es una solución robusta, defendible en entrevista técnica y lista para evolucionar a un entorno productivo.

```

```