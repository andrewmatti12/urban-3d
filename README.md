# Urban Design 3D Dashboard

Render real-world **OSM buildings** in 3D, ask **plain-English** questions (height, levels, area, type), click to inspect, and **save / load / delete** filter presets (“projects”).

---

## Premise

Give urban designers a quick, no-SQL way to:
- View a local cluster of buildings in 3D.
- Ask questions like “over 50 levels” or “residential under 30 m”.
- Save a few scenarios and share.

---

## How it Works (Architecture & Flow)

**Frontend (`client/`) — React + Three.js**
1. On load → `GET /api/buildings`
2. Extrudes building footprints into meshes (OrbitControls for pan/zoom)
3. Plain-English query → `POST /api/llm-filter` → highlight matches
4. Click a building → tooltip with details
5. Save / Load / Delete “projects” via API

**API (`server/`) — Flask**
- **Data source:** Overpass (OpenStreetMap)
- **Normalization:** height (m; ft→m), levels, area (m²; ft²→m²)
- **Caching:** SQLite `cache` table (fresh ≤ 6h, **stale fallback** on outage)
- **Projects:** SQLite tables `users`, `projects`
- **Health:** `/` and `/healthz`

**Deployment tools used:**  
- **Render** (backend, Flask/Gunicorn)  
- **Vercel** (frontend, Vite)  
- **GitHub** (version control)

---

## Tech Stack

- **Frontend:** React (Vite), Three.js + OrbitControls  
- **Backend:** Flask, Gunicorn, SQLite, `requests`, `flask-cors`, `python-dotenv`  
- **NLP Filter:** Robust regex first; optional Hugging Face Inference fallback  
- **UML:** Mermaid (`.mmd`)

---

## Project Structure

```
urban-3d/
├─ client/                  # React + Vite app
│  └─ src/App.jsx
├─ server/                  # Flask API
│  ├─ app.py
│  ├─ requirements.txt
│  └─ db.sqlite            # created/used at runtime
└─ uml/
   ├─ urban3d-class.mmd
   └─ urban3d-seq.mmd
```

---

## Environment Variables

**Frontend (`client`)**
- `VITE_API_BASE` → API base URL  
  - local: `http://localhost:5001`  
  - production: your Render URL (e.g., `https://your-api.onrender.com`)

**Backend (`server/.env`, optional)**
- `HF_API_KEY=hf_xxx` → only used if the regex parser can’t parse the query

### Getting a Hugging Face API key (optional)
1. Create / sign in at **https://huggingface.co**  
2. Go to **Settings → Access Tokens**  
3. Click **New token**, scope **Read** (name it e.g., `urban3d`)  
4. Copy the token (starts with `hf_`)  
5. Create `server/.env` with:
   ```
   HF_API_KEY=hf_********************************
   ```
6. **Do not commit** `.env` (already in `.gitignore`)

> Note: The app works **without** an HF key (regex first). The key lets the API fall back to HF Inference for ambiguous queries.

---

## Run Locally

### Prereqs
- **Node 18+**
- **Python 3.10+**

### 1) Start the API

**Windows PowerShell**
```powershell
cd server
python -m venv .venv
. .venv\Scripts\Activate.ps1
pip install -r requirements.txt
# Optional: New-Item -Name .env -ItemType File -Value "HF_API_KEY=hf_xxx"
python app.py     # serves http://localhost:5001
# (optional) warm cache once:
#   http://localhost:5001/api/buildings?refresh=1
```

**macOS/Linux**
```bash
cd server
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
# echo "HF_API_KEY=hf_xxx" > .env   # optional
python app.py
```

### 2) Start the Frontend
**New terminal**
```powershell
cd client
$env:VITE_API_BASE="http://localhost:5001"
npm install
npm run dev   # opens local Vite URL
```

(macOS/Linux)
```bash
cd client
export VITE_API_BASE="http://localhost:5001"
npm install
npm run dev
```

---

## API Overview

- `GET /` → `"Urban 3D API OK"`
- `GET /healthz` → `{"status":"ok"}`
- `GET /api/buildings[?refresh=1]` → buildings JSON (SQLite cache & stale fallback)
- `POST /api/llm-filter` → `{ filter, matching_ids }` from plain-English query
- `POST /api/save` → `{ ok, project_id }`
- `GET /api/projects?username=...` → saved projects
- `GET /api/load?project_id=...` → `{ filters:[...] }`
- `POST /api/delete` → `{ ok: boolean, deleted: n }`

---

## Query Cheatsheet

- **Levels:** `over 50 levels`, `<= 10 storeys`, `at least 40 floors`
- **Height:** `height < 100 ft`, `taller than 30 m`
- **Area:** `area > 2000 m²`, `area < 40000 ft²`
- **Type:** `residential`, `commercial`, `office`, `warehouse`, `school`, `church`, `hotel`, …

_Units_: ft→m, ft²→m²; meters/m² assumed by default.  
_Words_: stories/storeys/floors → **levels**.

---

## UML

- `uml/urban3d-class.mmd` — data model (User, Project)  
- `uml/urban3d-seq.mmd` — end-to-end interactions  
Preview with a Mermaid-enabled Markdown viewer or VS Code’s Mermaid extension.

---

## Notes

- **Cold starts:** Free hosting tiers (Render/Vercel) can sleep; first request may be slow.
- **Overpass limits:** Large/remote areas can rate-limit or time out; the API caches for 6h.

---

## License

MIT (sample/demo).
