[# Luraph v14.7 / v14.8 / v14.9 deobfuscator -- Railway Flask wrapper.

Modes:
  normal      -- full pipeline (hooks + devirt)
  no-hooks    -- skip VM closure instrumentation (no anti-tamper attribution)
  no-devirt   -- trace only, no lifting
  trace-only  -- alias for no-devirt

Timeout fixes for large files (13MB+):
  - Global timeout raised to 300s
  - Per-run STALL raised to 90s (monkey-patched into harness)
  - Spin watchdog always enabled from run 1 (DEOB_SPIN_LATE unset)
  - Budget raised to 120s

import os
import sys
import re
import shutil
import tempfile
import threading
import traceback
from pathlib import Path
from types import SimpleNamespace

from flask import Flask, request, render_template_string, jsonify

# ─────────────────────────────────────────────────────────────────────────────
# Locate the deobfuscator root (Deobfuscator/deobf/bin/) inside the repo.
# Adjust DEOBF_BIN if your directory layout differs.
# ─────────────────────────────────────────────────────────────────────────────
HERE = Path(__file__).resolve().parent
DEOBF_BIN = HERE / "Deobfuscator" / "deobf" / "bin"

if not DEOBF_BIN.is_dir():
    # fallback: maybe we're already inside deobf/
    for candidate in [HERE / "bin", HERE]:
        if (candidate / "harness.py").is_file():
            DEOBF_BIN = candidate
            break

if str(DEOBF_BIN) not in sys.path:
    sys.path.insert(0, str(DEOBF_BIN))

# ─────────────────────────────────────────────────────────────────────────────
# Monkey-patch harness.STALL before importing anything that uses it.
# Default is 20s -- way too short for 13MB files.
# ─────────────────────────────────────────────────────────────────────────────
import harness as _harness_mod
_harness_mod.STALL = int(os.environ.get("DEOBF_STALL", "90"))

# Force spin watchdog from the very first trace run.
os.environ.pop("DEOB_SPIN_LATE", None)

# ─────────────────────────────────────────────────────────────────────────────
# Imports that depend on sys.path being set
# ─────────────────────────────────────────────────────────────────────────────
import cli as _cli_mod
from cli import read_source, detect_version, load_engine, normalize_compat_args, Job

# ─────────────────────────────────────────────────────────────────────────────
# Flask app
# ─────────────────────────────────────────────────────────────────────────────
app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 64 * 1024 * 1024  # 64 MB upload limit

# ─────────────────────────────────────────────────────────────────────────────
# HTML template
# ─────────────────────────────────────────────────────────────────────────────
HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Luraph Deobfuscator</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: 'Segoe UI', system-ui, sans-serif;
    background: #0d1117;
    color: #e6edf3;
    min-height: 100vh;
    padding: 32px 16px;
  }
  .container { max-width: 760px; margin: 0 auto; }
  h1 { font-size: 1.6rem; margin-bottom: 4px; }
  .sub { color: #8b949e; font-size: 0.85rem; margin-bottom: 28px; }
  label { display: block; font-size: 0.8rem; color: #8b949e; margin-bottom: 6px; letter-spacing: .04em; text-transform: uppercase; }
  .drop-zone {
    border: 2px dashed #30363d;
    border-radius: 8px;
    padding: 40px;
    text-align: center;
    cursor: pointer;
    transition: border-color .2s, background .2s;
    margin-bottom: 20px;
    position: relative;
  }
  .drop-zone:hover, .drop-zone.drag { border-color: #58a6ff; background: #161b22; }
  .drop-zone input[type=file] {
    position: absolute; inset: 0; opacity: 0; cursor: pointer; width: 100%; height: 100%;
  }
  .drop-text { color: #8b949e; font-size: 0.9rem; pointer-events: none; }
  .drop-text span { color: #58a6ff; }
  .filename { color: #58a6ff; font-size: 0.85rem; margin-top: 8px; }
  .mode-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
    gap: 10px;
    margin-bottom: 20px;
  }
  .mode-card {
    border: 1px solid #30363d;
    border-radius: 8px;
    padding: 14px;
    cursor: pointer;
    transition: border-color .15s, background .15s;
    position: relative;
  }
  .mode-card:hover { border-color: #58a6ff; background: #161b22; }
  .mode-card input[type=radio] { position: absolute; opacity: 0; pointer-events: none; }
  .mode-card.selected { border-color: #58a6ff; background: #0d2137; }
  .mode-title { font-size: 0.9rem; font-weight: 600; margin-bottom: 4px; }
  .mode-desc { font-size: 0.75rem; color: #8b949e; line-height: 1.4; }
  .btn {
    width: 100%; padding: 14px; border: none; border-radius: 8px;
    background: #238636; color: #fff; font-size: 1rem; font-weight: 600;
    cursor: pointer; transition: background .15s;
    margin-bottom: 24px;
  }
  .btn:hover { background: #2ea043; }
  .btn:disabled { background: #21262d; color: #484f58; cursor: not-allowed; }
  .log-box {
    background: #161b22;
    border: 1px solid #30363d;
    border-radius: 8px;
    padding: 16px;
    font-family: 'Courier New', monospace;
    font-size: 0.78rem;
    color: #8b949e;
    min-height: 80px;
    max-height: 220px;
    overflow-y: auto;
    white-space: pre-wrap;
    word-break: break-all;
    margin-bottom: 20px;
    display: none;
  }
  .result-box {
    background: #161b22;
    border: 1px solid #238636;
    border-radius: 8px;
    padding: 16px;
    margin-bottom: 20px;
    display: none;
  }
  .result-box h3 { font-size: 0.9rem; color: #3fb950; margin-bottom: 12px; }
  .result-box textarea {
    width: 100%; height: 320px;
    background: #0d1117; border: 1px solid #30363d; border-radius: 6px;
    color: #e6edf3; font-family: 'Courier New', monospace;
    font-size: 0.78rem; padding: 10px; resize: vertical;
  }
  .dl-btn {
    margin-top: 10px; padding: 8px 18px;
    background: #1f6feb; border: none; border-radius: 6px;
    color: #fff; font-size: 0.85rem; cursor: pointer;
  }
  .dl-btn:hover { background: #388bfd; }
  .error-box {
    background: #2d1217; border: 1px solid #f85149;
    border-radius: 8px; padding: 16px;
    font-family: monospace; font-size: 0.8rem; color: #f85149;
    white-space: pre-wrap; word-break: break-all;
    display: none; margin-bottom: 20px;
  }
  .spinner { display: inline-block; width: 14px; height: 14px; border: 2px solid #fff3;
    border-top-color: #fff; border-radius: 50%; animation: spin .7s linear infinite; vertical-align: middle; margin-right: 8px; }
  @keyframes spin { to { transform: rotate(360deg); } }
  .tag { display: inline-block; font-size: 0.7rem; padding: 1px 6px; border-radius: 4px;
    background: #21262d; color: #8b949e; margin-left: 6px; vertical-align: middle; }
  .tag.slow { background: #1c2128; color: #e3b341; }
</style>
</head>
<body>
<div class="container">
  <h1>Luraph Deobfuscator</h1>
  <p class="sub">v14.7 / v14.8 / v14.9 -- powered by KryptIT engine</p>

  <label>Upload File (.lua / .luau / .txt)</label>
  <div class="drop-zone" id="dropZone">
    <input type="file" id="fileInput" accept=".lua,.luau,.txt">
    <div class="drop-text" id="dropText">
      Drop file here or <span>click to browse</span>
    </div>
    <div class="filename" id="fileName"></div>
  </div>

  <label>Mode</label>
  <div class="mode-grid">
    <div class="mode-card selected" data-mode="normal" onclick="selectMode(this)">
      <input type="radio" name="mode" value="normal" checked>
      <div class="mode-title">Normal <span class="tag slow">recommended</span></div>
      <div class="mode-desc">Full pipeline: VM instrumentation + devirtualization + lifting</div>
    </div>
    <div class="mode-card" data-mode="no-hooks" onclick="selectMode(this)">
      <input type="radio" name="mode" value="no-hooks">
      <div class="mode-title">No Hooks</div>
      <div class="mode-desc">Skip VM closure instrumentation -- use when stuck in loop on run 1</div>
    </div>
    <div class="mode-card" data-mode="no-devirt" onclick="selectMode(this)">
      <input type="radio" name="mode" value="no-devirt">
      <div class="mode-title">Trace Only</div>
      <div class="mode-desc">Capture behavior trace without devirtualization</div>
    </div>
    <div class="mode-card" data-mode="no-hooks-no-devirt" onclick="selectMode(this)">
      <input type="radio" name="mode" value="no-hooks-no-devirt">
      <div class="mode-title">No Hooks + Trace</div>
      <div class="mode-desc">No instrumentation, trace output only -- maximum compatibility</div>
    </div>
  </div>

  <button class="btn" id="runBtn" onclick="runDeobf()">Run Deobfuscator</button>

  <div class="log-box" id="logBox"></div>
  <div class="error-box" id="errorBox"></div>

  <div class="result-box" id="resultBox">
    <h3>✓ Deobfuscated Output</h3>
    <textarea id="resultText" readonly></textarea>
    <button class="dl-btn" onclick="download()">Download .lua</button>
  </div>
</div>

<script>
let selectedFile = null;
let selectedMode = 'normal';

const dropZone = document.getElementById('dropZone');
const fileInput = document.getElementById('fileInput');
const fileName = document.getElementById('fileName');
const dropText = document.getElementById('dropText');
const logBox = document.getElementById('logBox');
const errorBox = document.getElementById('errorBox');
const resultBox = document.getElementById('resultBox');
const resultText = document.getElementById('resultText');
const runBtn = document.getElementById('runBtn');

fileInput.addEventListener('change', () => {
  if (fileInput.files[0]) setFile(fileInput.files[0]);
});

dropZone.addEventListener('dragover', e => { e.preventDefault(); dropZone.classList.add('drag'); });
dropZone.addEventListener('dragleave', () => dropZone.classList.remove('drag'));
dropZone.addEventListener('drop', e => {
  e.preventDefault();
  dropZone.classList.remove('drag');
  if (e.dataTransfer.files[0]) setFile(e.dataTransfer.files[0]);
});

function setFile(f) {
  selectedFile = f;
  const mb = (f.size / 1024 / 1024).toFixed(2);
  fileName.textContent = `${f.name}  (${mb} MB)`;
  dropText.style.display = 'none';
}

function selectMode(card) {
  document.querySelectorAll('.mode-card').forEach(c => c.classList.remove('selected'));
  card.classList.add('selected');
  card.querySelector('input[type=radio]').checked = true;
  selectedMode = card.dataset.mode;
}

function log(msg) {
  logBox.style.display = 'block';
  logBox.textContent += msg + '\\n';
  logBox.scrollTop = logBox.scrollHeight;
}

function clearOutputs() {
  logBox.style.display = 'none';
  logBox.textContent = '';
  errorBox.style.display = 'none';
  errorBox.textContent = '';
  resultBox.style.display = 'none';
  resultText.value = '';
}

async function runDeobf() {
  if (!selectedFile) { alert('No file selected.'); return; }
  clearOutputs();
  runBtn.disabled = true;
  runBtn.innerHTML = '<span class="spinner"></span>Running...';
  log('[*] uploading ' + selectedFile.name + ' (' + (selectedFile.size / 1024 / 1024).toFixed(2) + ' MB)');
  log('[*] mode: ' + selectedMode);

  const fd = new FormData();
  fd.append('file', selectedFile);
  fd.append('mode', selectedMode);

  try {
    const resp = await fetch('/deobf', { method: 'POST', body: fd });
    const data = await resp.json();

    if (data.log) data.log.split('\\n').forEach(l => l && log(l));

    if (data.error) {
      errorBox.style.display = 'block';
      errorBox.textContent = data.error;
    } else if (data.output) {
      resultBox.style.display = 'block';
      resultText.value = data.output;
      log('[+] done -- ' + data.output.length + ' chars output');
    }
  } catch (e) {
    errorBox.style.display = 'block';
    errorBox.textContent = 'Network error: ' + e.message;
  } finally {
    runBtn.disabled = false;
    runBtn.innerHTML = 'Run Deobfuscator';
  }
}

function download() {
  const blob = new Blob([resultText.value], { type: 'text/plain' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'deobfuscated.lua';
  a.click();
}
</script>
</body>
</html>"""


# ─────────────────────────────────────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template_string(HTML)


@app.route("/deobf", methods=["POST"])
def deobf():
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "No file uploaded"}), 400

    mode = request.form.get("mode", "normal")

    log_lines = []
    def log(msg):
        log_lines.append(msg)

    workdir = None
    try:
        # Write uploaded file to a temp dir
        workdir = Path(tempfile.mkdtemp(prefix="luraph_web_"))
        inp = workdir / f.filename
        f.save(str(inp))

        source = read_source(inp)
        log(f"[*] file: {f.filename}  ({len(source)} chars)")

        # Auto-detect version
        version = detect_version(source)
        if version is None:
            return jsonify({
                "log": "\n".join(log_lines),
                "error": "[!] could not auto-detect Luraph version. "
                         "Make sure the file starts with the Luraph header banner."
            })
        log(f"[*] detected: Luraph v{version}")

        # Build args namespace that cli.Job / engine drivers expect
        args = SimpleNamespace(
            input=str(inp),
            output=None,
            engine=version,
            engine_resolved=version,
            # timing -- raised for large files
            timeout=300.0,
            budget=120.0,
            # executor
            executor="roblox",
            studio=False,
            input_text=None,
            # flags driven by UI mode
            no_hooks=(mode in ("no-hooks", "no-hooks-no-devirt")),
            no_devirt=(mode in ("no-devirt", "no-hooks-no-devirt")),
            # other pipeline options
            max_runs=12,
            devirt_rounds=200,
            strings=False,
            raw=False,
            no_fold=False,
            keep_harness=False,
            no_tidy=False,
            keep_preamble=False,
            trace_fallback=True,  # return trace when devirt fails
            debug=False,
            keep_work=False,
            no_credit=False,
            # compat flags normalize_compat_args fills in
            luau=None,
            bridge=None,
            cfg=[],
        )
        normalize_compat_args(args)

        log(f"[*] mode: {mode}  (no_hooks={args.no_hooks}  no_devirt={args.no_devirt})")
        log(f"[*] timeout={args.timeout}s  budget={args.budget}s  stall={_harness_mod.STALL}s")

        # Output file
        out_path = workdir / "deobfuscated.lua"
        args.output = str(out_path)

        engine = load_engine(version)

        # Use the same workdir as working directory for engine
        job_workdir = workdir / f".{inp.stem}_work"
        job_workdir.mkdir(exist_ok=True)

        job = Job(args, inp, source, job_workdir)

        # Run engine -- may take a while on 13MB files
        log(f"[*] starting engine...")
        result_path_str = engine.deobfuscate(job)

        if not result_path_str:
            return jsonify({
                "log": "\n".join(log_lines),
                "error": "[!] engine returned no output -- check server logs"
            })

        result_path = Path(result_path_str)
        if not result_path.is_file():
            return jsonify({
                "log": "\n".join(log_lines),
                "error": f"[!] engine output not found at: {result_path}"
            })

        output_text = result_path.read_text(encoding="latin-1", errors="replace")
        log(f"[+] output: {len(output_text)} chars")

        return jsonify({
            "log": "\n".join(log_lines),
            "output": output_text
        })

    except SystemExit as e:
        # cli.py uses sys.exit() for fatal errors
        msg = str(e)
        return jsonify({
            "log": "\n".join(log_lines),
            "error": msg
        })
    except Exception:
        tb = traceback.format_exc()
        return jsonify({
            "log": "\n".join(log_lines),
            "error": tb
        })
    finally:
        if workdir and workdir.exists():
            try:
                shutil.rmtree(workdir)
            except Exception:
                pass


# ─────────────────────────────────────────────────────────────────────────────
# Entry
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
]
