from flask import Flask, request, jsonify, render_template_string
import subprocess, tempfile, os

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024
DEOBF_PATH = "/app/Deobfuscator/deobf"

HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Luraph Deobfuscator</title>
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body { background: #0d0d0d; color: #e0e0e0; font-family: monospace; padding: 16px; }
h1 { color: #00ff88; margin-bottom: 16px; font-size: 1.2em; letter-spacing: 2px; }
.card { background: #141414; border: 1px solid #2a2a2a; border-radius: 10px; padding: 14px; margin-bottom: 14px; }
label { color: #555; font-size: 0.75em; display: block; margin-bottom: 6px; letter-spacing: 1px; }
textarea { width: 100%; background: #0a0a0a; color: #00ff88; border: 1px solid #2a2a2a; border-radius: 6px; padding: 10px; font-family: monospace; font-size: 0.72em; resize: vertical; min-height: 160px; outline: none; }
textarea:focus { border-color: #00ff88; }
input[type=file] { width: 100%; color: #aaa; background: #0a0a0a; border: 1px solid #2a2a2a; border-radius: 6px; padding: 8px; font-size: 0.8em; }
select { width: 100%; background: #0a0a0a; color: #aaa; border: 1px solid #2a2a2a; border-radius: 6px; padding: 8px; font-family: monospace; font-size: 0.8em; margin-top: 8px; }
.tabs { display: flex; gap: 8px; margin-bottom: 10px; }
.tab { padding: 6px 14px; border-radius: 4px; cursor: pointer; font-size: 0.8em; border: 1px solid #333; background: #1a1a1a; color: #666; }
.tab.active { background: #00ff88; color: #000; border-color: #00ff88; font-weight: bold; }
.btn-row { display: flex; gap: 8px; margin-top: 10px; flex-wrap: wrap; }
button { flex: 1; min-width: 80px; padding: 11px 8px; border: none; border-radius: 6px; font-family: monospace; font-size: 0.85em; cursor: pointer; font-weight: bold; }
#deobfBtn { background: #00ff88; color: #000; }
#deobfBtn:disabled { background: #1a4a30; color: #444; cursor: wait; }
#clearBtn { background: #1e1e1e; color: #aaa; border: 1px solid #333; }
#copyBtn { background: #0055cc; color: #fff; }
#dlBtn { background: #660066; color: #fff; }
#status { font-size: 0.8em; margin-top: 8px; min-height: 18px; }
#log { color: #444; font-size: 0.7em; margin-top: 8px; white-space: pre-wrap; max-height: 120px; overflow-y: auto; }
.hidden { display: none; }
.spinner { display: inline-block; animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
</style>
</head>
<body>
<h1>⚡ LURAPH DEOBFUSCATOR</h1>
<div class="card">
  <div class="tabs">
    <div class="tab active" onclick="switchTab('file')">📁 FILE</div>
    <div class="tab" onclick="switchTab('text')">📝 PASTE</div>
  </div>
  <div id="fileTab">
    <label>SELECT FILE (MAX 50MB)</label>
    <input type="file" id="fileInput" accept=".lua,.luau,.txt">
  </div>
  <div id="textTab" class="hidden">
    <label>PASTE CODE</label>
    <textarea id="textInput" placeholder="-- paste luraph code here..."></textarea>
  </div>
  <label style="margin-top:10px">MODE</label>
  <select id="modeSelect">
    <option value="auto">AUTO DETECT</option>
    <option value="trace">TRACE ONLY (fast, no devirt)</option>
    <option value="nohooks">NO HOOKS (skip stuck tracer)</option>
    <option value="full">FULL DEVIRT (slow)</option>
  </select>
  <div class="btn-row">
    <button id="deobfBtn" onclick="deobf()">▶ DEOBF</button>
    <button id="clearBtn" onclick="clearAll()">✕ CLEAR</button>
  </div>
  <div id="status"></div>
</div>
<div class="card">
  <label>OUTPUT</label>
  <textarea id="output" readonly placeholder="-- result here..."></textarea>
  <div class="btn-row">
    <button id="copyBtn" onclick="copyOut()">⧉ COPY</button>
    <button id="dlBtn" onclick="downloadOut()">↓ DOWNLOAD</button>
  </div>
  <div id="log"></div>
</div>
<script>
let activeTab = 'file';
function switchTab(tab) {
  activeTab = tab;
  document.querySelectorAll('.tab').forEach((t,i) => t.classList.toggle('active',(i===0&&tab==='file')||(i===1&&tab==='text')));
  document.getElementById('fileTab').classList.toggle('hidden', tab!=='file');
  document.getElementById('textTab').classList.toggle('hidden', tab!=='text');
}
async function deobf() {
  const btn = document.getElementById('deobfBtn');
  btn.disabled = true; btn.innerHTML = '<span class="spinner">⟳</span> WORKING...';
  let fd = new FormData();
  const mode = document.getElementById('modeSelect').value;
  fd.append('mode', mode);
  if (activeTab === 'file') {
    const file = document.getElementById('fileInput').files[0];
    if (!file) { setStatus('no file', '#ff4444'); resetBtn(); return; }
    fd.append('file', file);
  } else {
    const text = document.getElementById('textInput').value.trim();
    if (!text) { setStatus('no code', '#ff4444'); resetBtn(); return; }
    fd.append('file', new Blob([text], {type:'text/plain'}), 'input.lua');
  }
  setStatus('running... (1–5 min for large files)', '#ffaa00');
  try {
    const res = await fetch('/deobf', {method:'POST', body:fd});
    const data = await res.json();
    if (data.result) {
      document.getElementById('output').value = data.result;
      document.getElementById('log').textContent = data.log || '';
      setStatus('✓ done', '#00ff88');
    } else {
      setStatus('✗ ' + (data.error||'failed'), '#ff4444');
      document.getElementById('log').textContent = data.log || '';
    }
  } catch(e) { setStatus('✗ ' + e.message, '#ff4444'); }
  resetBtn();
}
function resetBtn() { const b=document.getElementById('deobfBtn'); b.disabled=false; b.innerHTML='▶ DEOBF'; }
function clearAll() { ['fileInput','textInput','output'].forEach(id=>document.getElementById(id).value=''); document.getElementById('log').textContent=''; setStatus('','#888'); }
function copyOut() { const o=document.getElementById('output').value; if(!o){setStatus('nothing to copy','#ff4444');return;} navigator.clipboard.writeText(o).then(()=>setStatus('✓ copied','#00ff88')); }
function downloadOut() { const o=document.getElementById('output').value; if(!o){setStatus('nothing','#ff4444');return;} const a=document.createElement('a'); a.href=URL.createObjectURL(new Blob([o],{type:'text/plain'})); a.download='deobfuscated.lua'; a.click(); setStatus('✓ downloading','#00ff88'); }
function setStatus(m,c) { const e=document.getElementById('status'); e.textContent=m; e.style.color=c; }
</script>
</body>
</html>"""

@app.route("/")
def index():
    return render_template_string(HTML)

@app.route("/deobf", methods=["POST"])
def deobf():
    f = request.files.get("file")
    mode = request.form.get("mode", "auto")
    if not f:
        return jsonify({"error": "no file"}), 400

    with tempfile.TemporaryDirectory() as tmp:
        input_path = os.path.join(tmp, "input.lua")
        output_path = os.path.join(tmp, "output.lua")
        f.save(input_path)

        cmd = ["python3", "cli.py", input_path, "-o", output_path,
               "--timeout", "240", "--trace-fallback"]

        if mode == "trace":
            cmd.append("--no-devirt")
        elif mode == "nohooks":
            cmd += ["--no-hooks", "--no-devirt"]
        elif mode == "full":
            cmd += ["--devirt-rounds", "400", "--max-runs", "20"]

        result = subprocess.run(cmd, cwd=DEOBF_PATH,
                                capture_output=True, text=True, timeout=300)

        if os.path.exists(output_path):
            with open(output_path) as out:
                return jsonify({"result": out.read(), "log": result.stderr})
        else:
            return jsonify({"error": "failed", "log": result.stderr}), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
