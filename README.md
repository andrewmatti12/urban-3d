# Urban Design 3D Dashboard

Render real-world **OSM buildings** in 3D, ask **plain-English** questions (height, levels, area, type), click to inspect, and **save/load/delete** filter presets (“projects”).

---

## Premise

Give urban designers a quick, no-SQL way to:
- See a local cluster of buildings in 3D.
- Ask questions like “over 50 levels” or “residential under 30 m”.
- Save a few scenarios and share.

---

## How it Works (Architecture & Flow)

**Frontend (client/)** — React + Three.js  
1. On load: `GET /api/buildings`  
2. Extrudes building footprints to meshes; OrbitControls for pan/zoom  
3. Plain-English query → `POST /api/llm-filter` → highlight matches  
4. Click a building → tooltip with details  
5. Save/Load/Delete “projects” via API

**API (server/)** — Flask  
- **Building data:** Overpass (OSM). Retries + backoff.  
- **Normalization:** height (meters; ft → m), levels, area (m²; ft² → m²).  
- **Caching:** SQLite `cache` table (fresh ≤ 6 h, **stale fallback** on failure).  
- **Projects:** SQLite tables `users`, `projects`.  
- Health endpoints: `/` and `/healthz`.

**Data Source** — OpenStreetMap via Overpass API.

---

## Tech Stack

- **Frontend:** React (Vite), Three.js + OrbitControls
- **Backend:** Flask, Gunicorn, SQLite, `requests`, `flask-cors`, `python-dotenv`
- **NLP Filter:** Regex first (robust); optional HF Inference fallback
- **UML:** Mermaid (`.mmd`)

**Deployment Tools (used):**  
- **Vercel** for the frontend (Vite)  
- **Render** for the backend (Flask/Gunicorn)  
- **GitHub** for version control

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

**Frontend** (`client`):  
- `VITE_API_BASE` → e.g. `http://localhost:5001` (local) or your Render URL in prod

**Backend** (`server/.env`, optional):  
- `HF_API_KEY=hf_xxx` (only used if regex can’t parse the query)

---

## Run Locally

### 1) Start the API (Windows PowerShell)
```powershell
cd server
python -m venv .venv
. .venv\Scripts\Activate.ps1
pip install -r requirements.txt
# Optional: New-Item -Name .env -ItemType File -Value "HF_API_KEY=hf_xxx"
python app.py          # http://localhost:5001
# (optional) warm cache once: http://localhost:5001/api/buildings?refresh=1
```

### 2) Start the Frontend (new terminal)
```powershell
cd client
$env:VITE_API_BASE="http://localhost:5001"
npm install
npm run dev            # opens a local Vite URL
```

(macOS/Linux equivalents)
```bash
# API
cd server
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py

# Frontend
cd client
export VITE_API_BASE="http://localhost:5001"
npm install
npm run dev
```

---

## API Overview

- `GET /` → `"Urban 3D API OK"`
- `GET /healthz` → `{"status":"ok"}`
- `GET /api/buildings[?refresh=1]` → buildings JSON (with SQLite cache & stale fallback)
- `POST /api/llm-filter` → `{ filter, matching_ids }` from plain-English query
- `POST /api/save` → `{ ok, project_id }`
- `GET /api/projects?username=…` → saved projects
- `GET /api/load?project_id=…` → `{ filters:[...] }`
- `POST /api/delete` → `{ ok: boolean, deleted: n }`

---

## Query Cheatsheet

- **Levels:** `over 50 levels`, `<= 10 storeys`, `at least 40 floors`
- **Height:** `height < 100 ft`, `taller than 30 m`
- **Area:** `area > 2000 m²`, `area < 40000 ft²`
- **Type:** `residential`, `commercial`, `office`, `warehouse`, `school`, `church`, `hotel`, …

Notes: ft → m, ft² → m², “stories/storeys/floors” → levels, meters & m² by default.

---

## UML

- `uml/urban3d-class.mmd` — data model (User, Project)
- `uml/urban3d-seq.mmd` — end-to-end interactions  
Preview with a Mermaid-enabled Markdown viewer or VS Code’s Mermaid extension.

---

## License

MIT (sample/demo).
