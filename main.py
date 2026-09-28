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
body { background: #0d0d0d; color: #e0e0e0; font-family: monospace; padding: 20px; }
h1 { color: #00ff88; margin-bottom: 20px; font-size: 1.3em; }
.box { background: #1a1a1a; border: 1px solid #333; border-radius: 8px; padding: 16px; margin-bottom: 16px; }
label { color: #888; font-size: 0.85em; display: block; margin-bottom: 8px; }
input[type=file] { width: 100%; color: #e0e0e0; background: #111; border: 1px solid #444; border-radius: 4px; padding: 8px; }
.btn-row { display: flex; gap: 10px; margin-top: 12px; }
button { flex: 1; padding: 12px; border: none; border-radius: 6px; font-family: monospace; font-size: 0.9em; cursor: pointer; font-weight: bold; }
#deobfBtn { background: #00ff88; color: #000; }
#clearBtn { background: #333; color: #e0e0e0; }
#copyBtn { background: #0088ff; color: #fff; }
#status { color: #ffaa00; font-size: 0.85em; margin-top: 10px; min-height: 20px; }
#output { width: 100%; min-height: 300px; background: #111; color: #00ff88; border: 1px solid #333; border-radius: 6px; padding: 12px; font-family: monospace; font-size: 0.75em; resize: vertical; white-space: pre; overflow: auto; }
.log { color: #666; font-size: 0.75em; margin-top: 8px; white-space: pre-wrap; max-height: 120px; overflow-y: auto; }
</style>
</head>
<body>
<h1>⚡ Luraph Deobfuscator</h1>
<div class="box">
  <label>SELECT .LUA FILE (max 50MB)</label>
  <input type="file" id="fileInput" accept=".lua,.luau">
  <div class="btn-row">
    <button id="deobfBtn" onclick="deobf()">DEOBF</button>
    <button id="clearBtn" onclick="clearAll()">CLEAR</button>
  </div>
  <div id="status"></div>
</div>
<div class="box">
  <label>OUTPUT</label>
  <textarea id="output" readonly placeholder="// result appears here..."></textarea>
  <div class="btn-row">
    <button id="copyBtn" onclick="copyOut()">COPY</button>
  </div>
  <div class="log" id="log"></div>
</div>
<script>
async function deobf() {
  const file = document.getElementById('fileInput').files[0];
  if (!file) { setStatus('no file selected', '#ff4444'); return; }
  setStatus('uploading...', '#ffaa00');
  const fd = new FormData();
  fd.append('file', file);
  try {
    setStatus('deobfuscating... (may take 1-3 min)', '#ffaa00');
    const res = await fetch('/deobf', { method: 'POST', body: fd });
    const data = await res.json();
    if (data.result) {
      document.getElementById('output').value = data.result;
      document.getElementById('log').textContent = data.log || '';
      setStatus('done ✓', '#00ff88');
    } else {
      setStatus('failed: ' + (data.error || 'unknown'), '#ff4444');
      document.getElementById('log').textContent = data.log || '';
    }
  } catch(e) {
    setStatus('error: ' + e.message, '#ff4444');
  }
}
function clearAll() {
  document.getElementById('fileInput').value = '';
  document.getElementById('output').value = '';
  document.getElementById('log').textContent = '';
  setStatus('', '#888');
}
function copyOut() {
  const out = document.getElementById('output');
  if (!out.value) { setStatus('nothing to copy', '#ff4444'); return; }
  navigator.clipboard.writeText(out.value).then(() => setStatus('copied ✓', '#00ff88'));
}
function setStatus(msg, color) {
  const el = document.getElementById('status');
  el.textContent = msg;
  el.style.color = color;
}
</script>
</body>
</html>"""

@app.route("/")
def index():
    return render_template_string(HTML)

@app.route("/deobf", methods=["POST"])
def deobf():
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "no file"}), 400
    with tempfile.TemporaryDirectory() as tmp:
        input_path = os.path.join(tmp, "input.lua")
        output_path = os.path.join(tmp, "output.lua")
        f.save(input_path)
        result = subprocess.run(
            ["python3", "cli.py", input_path, "-o", output_path,
             "--timeout", "240", "--trace-fallback"],
            cwd=DEOBF_PATH,
            capture_output=True, text=True, timeout=300
        )
        if os.path.exists(output_path):
            with open(output_path) as out:
                return jsonify({"result": out.read(), "log": result.stderr})
        else:
            return jsonify({"error": "failed", "log": result.stderr}), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
