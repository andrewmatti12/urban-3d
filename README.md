# Urban Design 3D Dashboard

React + Three.js frontend, Flask API backend, Overpass(OSM) buildings. Query with plain English (levels, height, area, type), click to inspect, save/load/delete projects.

## Tech
- Frontend: React (Vite), Three.js (OrbitControls)
- Backend: Flask, SQLite, requests, dotenv
- LLM: Hugging Face Inference (optional) – regex parser used first

---

## 1) Local Setup

### Prereqs
- **Node 18+**
- **Python 3.10+**

### Backend (Flask)
```bash
cd server
python -m venv .venv
# Windows PowerShell
. .venv/Scripts/Activate.ps1
# macOS/Linux
# source .venv/bin/activate

pip install -r requirements.txt

# create .env (optional if you skip HF)
echo HF_API_KEY=hf_xxx >> .env

python app.py   # http://localhost:5001
