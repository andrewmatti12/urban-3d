import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";

const API = import.meta.env.VITE_API_BASE || "http://localhost:5001";

const titleCase = (s) =>
  (s || "")
    .replace(/[_-]+/g, " ")
    .replace(/\w\S*/g, (t) => t[0].toUpperCase() + t.slice(1).toLowerCase());

function Sidebar({ username, setUsername, query, setQuery, onRunQuery, onSave, projects, onLoadProject, onDeleteProject }) {
  return (
    <div className="sidebar">
      <h2>Urban Design 3D Dashboard</h2>

      <div className="row">
        <input value={username} onChange={e=>setUsername(e.target.value)} placeholder="Username" style={{flex:1}}/>
      </div>

      <div className="row">
        <input value={query} onChange={e=>setQuery(e.target.value)} placeholder='Try: "buildings over 20 m"' style={{flex:1}}/>
        <button className="button" onClick={onRunQuery}>Run</button>
      </div>

      <div className="row">
        <input id="projName" placeholder="Project name" style={{flex:1}}/>
        <button className="button" onClick={()=>{
          const name = document.getElementById("projName").value.trim();
          if (name) onSave(name);
        }}>Save Project</button>
      </div>

      <h3>Saved projects</h3>
      <ul style={{listStyle:"none", padding:0, margin:0}}>
        {projects.map(p => (
          <li key={p.id} style={{display:"flex", gap:8, alignItems:"center", marginBottom:6}}>
            <button className="button" onClick={()=>onLoadProject(p.id)} style={{flex:1, textAlign:"left"}}>
              {p.name} <small>({new Date(p.created_at).toLocaleString()})</small>
            </button>
            <button className="button" onClick={()=>onDeleteProject(p.id)} title="Delete">Delete</button>
          </li>
        ))}
      </ul>
      <p style={{fontSize:12,opacity:.7}}>Tip: click a building in the 3D view to see details.</p>
    </div>
  );
}

function Map3D({ buildings, highlightedIds, onPick }) {
  const mountRef = useRef();
  const sceneRef = useRef();
  const cameraRef = useRef();
  const controlsRef = useRef();
  const meshesRef = useRef(new Map());
  const [ready, setReady] = useState(false);

  // Scene + controls
  useEffect(() => {
    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0xf5f7fb);
    const camera = new THREE.PerspectiveCamera(50, 1, 0.1, 10000);
    const renderer = new THREE.WebGLRenderer({ antialias: true });
    sceneRef.current = scene;
    cameraRef.current = camera;

    const mount = mountRef.current;
    mount.appendChild(renderer.domElement);

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.05;
    controls.screenSpacePanning = true;
    controls.maxPolarAngle = Math.PI / 2.05;
    controls.minDistance = 50;
    controls.maxDistance = 4000;
    controlsRef.current = controls;

    const resize = () => {
      const w = mount.clientWidth, h = mount.clientHeight;
      camera.aspect = w/h; camera.updateProjectionMatrix();
      renderer.setSize(w, h, false);
    };
    window.addEventListener("resize", resize);

    camera.position.set(300, 300, 600);
    controls.target.set(0, 0, 0);
    camera.lookAt(0, 0, 0);

    scene.add(new THREE.AmbientLight(0xffffff, 0.8));
    const dir = new THREE.DirectionalLight(0xffffff, 0.6);
    dir.position.set(120, -80, 200);
    scene.add(dir);

    const ground = new THREE.Mesh(
      new THREE.PlaneGeometry(4000, 4000),
      new THREE.MeshLambertMaterial({ color: 0x9aa0a6 })
    );
    ground.rotation.x = -Math.PI/2;
    ground.position.y = 0;
    scene.add(ground);

    const raycaster = new THREE.Raycaster();
    const mouse = new THREE.Vector2();
    const onClick = (e) => {
      const rect = renderer.domElement.getBoundingClientRect();
      mouse.x = ((e.clientX-rect.left)/rect.width)*2 - 1;
      mouse.y = -((e.clientY-rect.top)/rect.height)*2 + 1;
      raycaster.setFromCamera(mouse, camera);
      const hits = raycaster.intersectObjects([...meshesRef.current.values()], false);
      if (hits.length) onPick(hits[0].object.userData.building);
    };
    renderer.domElement.addEventListener("click", onClick);

    const tick = () => { controls.update(); renderer.render(scene, camera); requestAnimationFrame(tick); };
    requestAnimationFrame(tick);
    setReady(true);
    resize();

    return () => {
      window.removeEventListener("resize", resize);
      renderer.domElement.removeEventListener("click", onClick);
      renderer.dispose();
      controls.dispose();
      mount.removeChild(renderer.domElement);
    };
  }, []);

  // Build meshes + fit view (center on X/Z only)
  useEffect(() => {
    if (!ready) return;
    const scene = sceneRef.current;
    for (const m of meshesRef.current.values()) scene.remove(m);
    meshesRef.current.clear();

    if (!buildings?.length) return;

    const lat0 = buildings[0].coords[0][0];
    const lon0 = buildings[0].coords[0][1];
    const R = 6378137.0;
    const toXY = (lat, lon) => {
      const x = THREE.MathUtils.degToRad(lon - lon0) * R * Math.cos(THREE.MathUtils.degToRad((lat+lat0)/2));
      const y = THREE.MathUtils.degToRad(lat - lat0) * R;
      return new THREE.Vector2(x, y);
    };

    const meshes = [];
    buildings.forEach(b => {
      const ring = b.coords.map(([lat, lon]) => toXY(lat, lon));
      const shape = new THREE.Shape(ring.map(v => new THREE.Vector2(v.x, v.y)));
      const geom = new THREE.ExtrudeGeometry(shape, { depth: b.height_m, bevelEnabled:false });
      geom.rotateX(-Math.PI / 2); // extrude upward (+Y)
      const mat = new THREE.MeshLambertMaterial({ color: 0x6aaefc });
      const mesh = new THREE.Mesh(geom, mat);
      mesh.userData.building = b;
      meshesRef.current.set(b.id, mesh);
      scene.add(mesh);
      meshes.push(mesh);
    });

    const box = new THREE.Box3();
    meshes.forEach(m => box.expandByObject(m));
    const size = new THREE.Vector3(); box.getSize(size);
    const center = new THREE.Vector3(); box.getCenter(center);

    const offset = new THREE.Vector3(center.x, 0, center.z);
    meshes.forEach(m => m.position.sub(offset));

    const cam = cameraRef.current, controls = controlsRef.current;
    const maxHoriz = Math.max(size.x, size.z);
    const dist = Math.max(200, maxHoriz * 1.2);

    cam.position.set(dist, Math.max(150, maxHoriz * 0.6), dist);
    controls.target.set(0, 0, 0);
    cam.lookAt(0, 0, 0);
  }, [buildings, ready]);

  // Highlight effect
  useEffect(() => {
    for (const [id, mesh] of meshesRef.current) {
      mesh.material.color.set(highlightedIds?.includes(id) ? 0xff6b6b : 0x6aaefc);
    }
  }, [highlightedIds]);

  return <div ref={mountRef} style={{width:"100%", height:"100%"}} />;
}

export default function App() {
  const [buildings, setBuildings] = useState([]);
  const [highlighted, setHighlighted] = useState([]);
  const [username, setUsername] = useState("");
  const [query, setQuery] = useState("");
  const [projects, setProjects] = useState([]);
  const [picked, setPicked] = useState(null);
  const [selectedId, setSelectedId] = useState(null); // NEW: click-to-highlight

  const fetchBuildings = async () => {
    const r = await fetch(`${API}/api/buildings`);
    const j = await r.json();
    setBuildings(j.buildings || []);
    setHighlighted([]); setPicked(null); setSelectedId(null);
  };

  const runQuery = async () => {
    setSelectedId(null); // clear manual selection on new query
    const r = await fetch(`${API}/api/llm-filter`, {
      method: "POST", headers: {"Content-Type":"application/json"},
      body: JSON.stringify({ query, buildings })
    });
    const j = await r.json();
    setHighlighted(j.matching_ids || []);
  };

  const saveProject = async (name) => {
    if (!username) { alert("Enter a username first."); return; }
    const r = await fetch(`${API}/api/save`, {
      method: "POST", headers: {"Content-Type":"application/json"},
      body: JSON.stringify({ username, project_name: name, filters: [{ query }] })
    });
    const j = await r.json();
    if (j.ok) { alert("Saved."); loadProjects(); }
  };

  const loadProjects = async () => {
    if (!username) return;
    const r = await fetch(`${API}/api/projects?username=${encodeURIComponent(username)}`);
    const j = await r.json();
    setProjects(j);
  };

  const loadOne = async (id) => {
    setSelectedId(null); // clear manual selection on load
    const r = await fetch(`${API}/api/load?project_id=${id}`);
    const j = await r.json();
    let union = [];
    for (const f of j.filters) {
      const rr = await fetch(`${API}/api/llm-filter`, {
        method: "POST", headers: {"Content-Type":"application/json"},
        body: JSON.stringify({ query: f.query, buildings })
      });
      const jj = await rr.json();
      union = [...new Set([...union, ...(jj.matching_ids||[])])];
    }
    setHighlighted(union);
  };

  // delete project
  const deleteProject = async (id) => {
    if (!username) { alert("Enter a username first."); return; }
    if (!confirm("Delete this project?")) return;
    const r = await fetch(`${API}/api/delete`, {
      method: "POST",
      headers: {"Content-Type":"application/json"},
      body: JSON.stringify({ username, project_id: id })
    });
    const j = await r.json();
    if (j.ok) loadProjects();
    else alert(j.error || "Delete failed.");
  };

  useEffect(() => { fetchBuildings(); }, []);
  useEffect(() => { loadProjects(); }, [username]);

  return (
    <div className="app">
      <Sidebar
        username={username} setUsername={setUsername}
        query={query} setQuery={setQuery}
        onRunQuery={runQuery}
        onSave={saveProject}
        projects={projects}
        onLoadProject={loadOne}
        onDeleteProject={deleteProject}
      />
      <div style={{position:"relative"}}>
        <Map3D
          buildings={buildings}
          highlightedIds={[
            ...highlighted,
            ...(selectedId ? [selectedId] : [])
          ]}
          onPick={(b) => { setPicked(b); setSelectedId(b.id); }}
        />
        <div id="tooltip">
          {picked ? (
            <>
              <b>{picked.address}</b><br/>
              Type: {titleCase(picked.type)}<br/>
              Height: {picked.height_m} m<br/>
              Levels: {picked.levels}<br/>
              Area: {picked.area_m2} m²
            </>
          ) : <>Click a building to see details</>}
        </div>
      </div>
    </div>
  );
}