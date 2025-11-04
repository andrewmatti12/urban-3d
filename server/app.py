import os, json, math, sqlite3, re, time
from datetime import datetime, timedelta
from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
from dotenv import load_dotenv

# load .env (HF_API_KEY in server/.env)
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

app = Flask(__name__)
CORS(app)

HF_API_KEY = os.getenv("HF_API_KEY") or ""
HF_MODEL_URL = "https://api-inference.huggingface.co/models/google/flan-t5-base"
OVERPASS_URL = "https://overpass-api.de/api/interpreter"

# Calgary bbox ~ several blocks
DEFAULT_BBOX = {"west": -114.0715, "south": 51.0455, "east": -114.0665, "north": 51.0493}

DB_PATH = os.path.join(os.path.dirname(__file__), "db.sqlite")

# -------------------------------- DB --------------------------------
def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    con = db(); cur = con.cursor()
    cur.execute("""CREATE TABLE IF NOT EXISTS users(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL)""")
    cur.execute("""CREATE TABLE IF NOT EXISTS projects(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        filters_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY(user_id) REFERENCES users(id))""")
    # cache table for /api/buildings
    cur.execute("""CREATE TABLE IF NOT EXISTS cache(
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL,
        updated_at TEXT NOT NULL)""")
    con.commit(); con.close()
init_db()

def cache_get(key, max_age_seconds):
    con = db(); cur = con.cursor()
    cur.execute("SELECT value, updated_at FROM cache WHERE key=?", (key,))
    row = cur.fetchone(); con.close()
    if not row: return None
    updated = datetime.fromisoformat(row["updated_at"])
    if datetime.utcnow() - updated > timedelta(seconds=max_age_seconds):
        return None
    return json.loads(row["value"])

def cache_put(key, value_obj):
    con = db(); cur = con.cursor()
    cur.execute("INSERT OR REPLACE INTO cache(key,value,updated_at) VALUES(?,?,?)",
                (key, json.dumps(value_obj), datetime.utcnow().isoformat()))
    con.commit(); con.close()

# -------------------------------- geometry helpers --------------------------------
def to_meters_xy(lat, lon, lat0, lon0):
    R = 6378137.0
    x = math.radians(lon - lon0) * R * math.cos(math.radians((lat + lat0) / 2.0))
    y = math.radians(lat - lat0) * R
    return x, y

def polygon_area_m2(coords, lat0, lon0):
    pts = [to_meters_xy(lat, lon, lat0, lon0) for (lat, lon) in coords]
    s = 0.0
    for i in range(len(pts)-1):
        x1,y1 = pts[i]; x2,y2 = pts[i+1]
        s += (x1*y2 - x2*y1)
    return abs(s) * 0.5

def estimate_height(tags):
    h = None
    if 'height' in tags:
        try:
            m = re.findall(r"[0-9]+(?:\.[0-9]+)?", tags['height'])
            if m: h = float(m[0])
        except: pass
    if h is None:
        for k in ('building:levels','levels'):
            if k in tags:
                try:
                    h = float(re.findall(r"[0-9]+(?:\.[0-9]+)?", tags[k])[0]) * 3.0
                    break
                except: pass
    return round(float(h if h is not None else 9.0), 2)

# -------------------------------- Overpass (retries) --------------------------------
_requests = requests.Session()
_requests.headers.update({"User-Agent": "urban-3d/1.0 (contact: none)"})

def _overpass_fetch_json(bbox, retries=3, backoff=2.0):
    q = f"""
    [out:json][timeout:60];
    ( way["building"]({bbox['south']},{bbox['west']},{bbox['north']},{bbox['east']}); );
    (._;>;); out body;
    """
    last_err = None
    for attempt in range(1, retries+1):
        try:
            r = _requests.post(OVERPASS_URL, data=q, timeout=70)
            if r.status_code in (429, 500, 502, 503, 504):
                last_err = RuntimeError(f"Overpass {r.status_code}")
                time.sleep(backoff * attempt); continue
            r.raise_for_status()
            return r.json()
        except Exception as e:
            last_err = e
            time.sleep(backoff * attempt)
    raise last_err

def _buildings_from_overpass_json(bbox, data):
    nodes = {el["id"]: (el["lat"], el["lon"]) for el in data.get("elements", []) if el["type"] == "node"}
    lat0 = (bbox['south'] + bbox['north'])/2
    lon0 = (bbox['west'] + bbox['east'])/2
    buildings = []
    for el in data.get("elements", []):
        if el["type"] != "way": continue
        nds = el.get("nodes", [])
        if len(nds) < 4: continue
        if nds[0] != nds[-1]: nds = nds + [nds[0]]
        try:
            ring = [nodes[nid] for nid in nds]
        except KeyError:
            continue
        tags = el.get("tags", {})
        buildings.append({
            "id": el["id"],
            "address": " ".join(filter(None, [tags.get("addr:housenumber"), tags.get("addr:street")])) or tags.get("name") or "Unknown",
            "type": tags.get("building") or "building",
            "height_m": estimate_height(tags),
            "area_m2": round(polygon_area_m2(ring, lat0, lon0), 2),
            "levels": tags.get("building:levels") or tags.get("levels") or "N/A",
            "coords": ring
        })
    return buildings

# -------------------------------- LLM / parsing --------------------------------
FT_TO_M = 0.3048
FT2_TO_M2 = 0.092903

LEVEL_WORDS_RE = r"(?:level|levels|storey|storeys|story|stories|floor|floors)"
AREA_WORDS_RE  = r"(?:area|sqm|m2|m²|square\s*met(?:er|re)s?|sq\s*ft|ft2|ft²)"
HEIGHT_WORDS_RE = r"(?:height|tall)"

def _normalize_height_value_from_text(original_text: str, value_str: str) -> float:
    v = float(value_str)
    if re.search(r"\b(feet|foot|ft)\b", original_text, re.I):
        return v * FT_TO_M
    return v

def _normalize_area_value_from_text(original_text: str, value_str: str) -> float:
    v = float(value_str)
    if re.search(r"(sq\s*ft|ft2|ft²|square\s*feet)", original_text, re.I):
        return v * FT2_TO_M2
    return v  # assume m² by default

def _fallback_parse(user_text: str):
    """Regex parser: understands 'over/under/at least/at most', units, and synonyms."""
    txt = user_text.strip()

    # type queries e.g., "commercial buildings"
    KNOWN_TYPES = ["commercial","retail","office","residential","apartments","house","industrial","warehouse","school","church","hospital","hotel"]
    found_types = [t for t in KNOWN_TYPES if re.search(rf"\b{re.escape(t)}\b", txt, re.I)]
    if found_types:
        return {"attribute": "type", "operator": "in", "value": found_types}

    # explicit attribute before number
    m = re.search(
        rf"\b(height|{LEVEL_WORDS_RE}|area)\b.*?(>=|<=|>|<|=)?\s*([0-9]+(?:\.[0-9]+)?)\s*(m|meter|meters|metre|metres|m2|m²|sq\s*ft|ft2|ft²|feet|foot|ft)?",
        txt, re.I)
    if m:
        attr_raw = m.group(1).lower()
        op = m.group(2) or ">"
        val = m.group(3)
        unit = (m.group(4) or "").lower()

        if re.fullmatch(LEVEL_WORDS_RE, attr_raw, re.I):
            return {"attribute": "levels", "operator": op, "value": val}
        if attr_raw == "area":
            value = _normalize_area_value_from_text(txt + " " + unit, val)
            return {"attribute": "area_m2", "operator": op, "value": str(value)}
        # height
        value = _normalize_height_value_from_text(txt + " " + unit, val)
        return {"attribute": "height_m", "operator": op, "value": str(value)}

    # wordy form: "over 50 levels", "at least 200 ft", etc.
    m2 = re.search(
        rf"\b(over|more than|greater than|at least|minimum|min|under|less than|no more than|at most|max|maximum)\b\s*([0-9]+(?:\.[0-9]+)?)\s*(m|meter|meters|metre|metres|m2|m²|sq\s*ft|ft2|ft²|feet|foot|ft)?",
        txt, re.I)
    if m2:
        word = m2.group(1).lower()
        op = ">" if word in ("over","more than","greater than","at least","minimum","min") else "<="
        val = m2.group(2)
        unit = (m2.group(3) or "").lower()

        if re.search(LEVEL_WORDS_RE, txt, re.I):
            return {"attribute": "levels", "operator": op, "value": val}
        if re.search(AREA_WORDS_RE, txt, re.I):
            value = _normalize_area_value_from_text(txt + " " + unit, val)
            return {"attribute": "area_m2", "operator": op, "value": str(value)}
        value = _normalize_height_value_from_text(txt + " " + unit, val)
        return {"attribute": "height_m", "operator": op, "value": str(value)}

    return None

def llm_extract_filter(user_text):
    """Prefer regex parser; fall back to HF only if regex fails."""
    flt = _fallback_parse(user_text)
    if flt:
        return flt

    if HF_API_KEY:
        try:
            headers = {"Authorization": f"Bearer {HF_API_KEY}"}
            prompt = (
                "Extract one filter from this query as strict JSON with keys attribute, operator, value. "
                "Attributes: height_m, levels, area_m2, type. Operators: >, >=, <, <=, =, in. "
                "If asking for a type, use operator 'in' and value as a list. "
                f"Query: {user_text}\nJSON:"
            )
            resp = requests.post(HF_MODEL_URL, headers=headers,
                                 json={"inputs": prompt, "parameters": {"max_new_tokens": 80}},
                                 timeout=60)
            resp.raise_for_status()
            out = resp.json()
            text = out[0]["generated_text"] if isinstance(out, list) and out else out.get("generated_text","")
            jm = re.search(r"\{.*\}", text, re.S)
            if jm:
                flt = json.loads(jm.group(0))
                a = flt.get("attribute","").lower()
                if a in ("height","height_m"): flt["attribute"] = "height_m"
                elif a in ("area","area_m2"): flt["attribute"] = "area_m2"
                elif re.fullmatch(LEVEL_WORDS_RE, a): flt["attribute"] = "levels"
                if flt.get("attribute") == "height_m" and flt.get("value") is not None:
                    flt["value"] = str(_normalize_height_value_from_text(user_text, str(flt["value"])) )
                if flt.get("attribute") == "area_m2" and flt.get("value") is not None:
                    flt["value"] = str(_normalize_area_value_from_text(user_text, str(flt["value"])) )
                return flt
        except Exception:
            pass
    return None

def apply_filter(buildings, flt):
    if not flt:
        return []  # don't highlight everything on unparsed queries
    attr = flt.get("attribute","")
    op = flt.get("operator","")
    val = flt.get("value")

    def match(b):
        if attr == "height_m":
            x = float(b["height_m"]); y = float(val)
        elif attr == "levels":
            try: x = float(b["levels"]); y = float(val)
            except: return False
        elif attr == "area_m2":
            x = float(b["area_m2"]); y = float(val)
        elif attr == "type":
            items = [s.strip().lower() for s in (val if isinstance(val,list) else [val])]
            if op == "in": return any(k in (b["type"] or "").lower() for k in items)
            return (b["type"] or "").lower() == str(val).lower()
        else:
            return False

        if op == ">": return x > y
        if op == ">=": return x >= y
        if op == "<": return x < y
        if op == "<=": return x <= y
        if op == "=": return abs(x - y) < 1e-9
        return False

    return [b["id"] for b in buildings if match(b)]

# -------------------------------- Routes --------------------------------
@app.get("/")
def root():
    return "Urban 3D API OK", 200

@app.get("/healthz")
def healthz():
    return jsonify({"status":"ok"}), 200

@app.get("/api/buildings")
def api_buildings():
    bbox = {
        "west": float(request.args.get("west", DEFAULT_BBOX["west"])),
        "south": float(request.args.get("south", DEFAULT_BBOX["south"])),
        "east": float(request.args.get("east", DEFAULT_BBOX["east"])),
        "north": float(request.args.get("north", DEFAULT_BBOX["north"])),
    }
    force = request.args.get("refresh") in ("1","true","yes")
    key = f"b:{bbox['west']:.5f},{bbox['south']:.5f},{bbox['east']:.5f},{bbox['north']:.5f}"

    # 1) serve fresh cache (6 hours)
    if not force:
        cached = cache_get(key, max_age_seconds=6*60*60)
        if cached:
            cached["source"] = "cache"
            return jsonify(cached)

    # 2) fetch live with retries
    try:
        data = _overpass_fetch_json(bbox)
        blds = _buildings_from_overpass_json(bbox, data)
        payload = {"bbox": bbox, "count": len(blds), "buildings": blds}
        cache_put(key, payload)
        payload["source"] = "live"
        return jsonify(payload)
    except Exception as e:
        # 3) stale fallback if available
        stale = cache_get(key, max_age_seconds=365*24*60*60)
        if stale:
            stale["source"] = "stale-cache"
            stale["warning"] = f"live fetch failed: {e}"
            return jsonify(stale)
        return jsonify({"error": str(e)}), 500

@app.post("/api/llm-filter")
def api_llm_filter():
    data = request.get_json(force=True)
    query = data.get("query","")
    blds = data.get("buildings", [])
    flt = llm_extract_filter(query)
    if not flt:
        return jsonify({"filter": None, "matching_ids": [], "reason": "Could not parse a filter from the query."})
    ids = apply_filter(blds, flt) if blds else []
    return jsonify({"filter": flt, "matching_ids": ids})

@app.post("/api/save")
def api_save():
    data = request.get_json(force=True)
    username = data.get("username","").strip()
    name = data.get("project_name","").strip()
    filters = data.get("filters", [])
    if not username or not name:
        return jsonify({"error":"username and project_name required"}), 400
    con = db(); cur = con.cursor()
    cur.execute("INSERT OR IGNORE INTO users(username) VALUES (?)", (username,))
    cur.execute("SELECT id FROM users WHERE username=?", (username,))
    uid = cur.fetchone()["id"]
    cur.execute("INSERT INTO projects(user_id,name,filters_json,created_at) VALUES (?,?,?,?)",
                (uid, name, json.dumps(filters), datetime.utcnow().isoformat()))
    con.commit(); pid = cur.lastrowid; con.close()
    return jsonify({"ok": True, "project_id": pid})

@app.get("/api/projects")
def api_projects():
    username = request.args.get("username","").strip()
    if not username: return jsonify([])
    con = db(); cur = con.cursor()
    cur.execute("SELECT id FROM users WHERE username=?", (username,))
    row = cur.fetchone()
    if not row:
        con.close(); return jsonify([])
    uid = row["id"]
    cur.execute("SELECT id,name,created_at FROM projects WHERE user_id=? ORDER BY id DESC", (uid,))
    rows = [dict(r) for r in cur.fetchall()]
    con.close()
    return jsonify(rows)

@app.get("/api/load")
def api_load():
    pid = request.args.get("project_id")
    con = db(); cur = con.cursor()
    cur.execute("SELECT filters_json FROM projects WHERE id=?", (pid,))
    row = cur.fetchone(); con.close()
    if not row: return jsonify({"error":"not found"}), 404
    return jsonify({"filters": json.loads(row["filters_json"])})

# delete a project owned by the username
@app.post("/api/delete")
def api_delete():
    data = request.get_json(force=True)
    username = data.get("username","").strip()
    pid = data.get("project_id")
    if not username or not pid:
        return jsonify({"ok": False, "error": "username and project_id required"}), 400
    con = db(); cur = con.cursor()
    cur.execute("SELECT id FROM users WHERE username=?", (username,))
    row = cur.fetchone()
    if not row:
        con.close(); return jsonify({"ok": False, "error": "user not found"}), 404
    uid = row["id"]
    cur.execute("DELETE FROM projects WHERE id=? AND user_id=?", (pid, uid))
    con.commit()
    deleted = cur.rowcount
    con.close()
    return jsonify({"ok": deleted > 0, "deleted": deleted})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5001"))
    app.run(host="0.0.0.0", port=port)
