import os
import sys
import re
import shutil
import tempfile
import traceback
from pathlib import Path
from types import SimpleNamespace

from flask import Flask, request, render_template_string, jsonify

HERE = Path(__file__).resolve().parent
DEOBF_BIN = HERE / "Deobfuscator" / "deobf" / "bin"

if not DEOBF_BIN.is_dir():
    for candidate in [HERE / "bin", HERE]:
        if (candidate / "harness.py").is_file():
            DEOBF_BIN = candidate
            break

if str(DEOBF_BIN) not in sys.path:
    sys.path.insert(0, str(DEOBF_BIN))

import harness as _harness_mod
_harness_mod.STALL = int(os.environ.get("DEOBF_STALL", "90"))
os.environ.pop("DEOB_SPIN_LATE", None)

from cli import read_source, detect_version, load_engine, normalize_compat_args, Job

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 64 * 1024 * 1024

HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Luraph Deobfuscator</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:system-ui,sans-serif;background:#0d1117;color:#e6edf3;min-height:100vh;padding:32px 16px}
.container{max-width:720px;margin:0 auto}
h1{font-size:1.5rem;margin-bottom:4px}
.sub{color:#8b949e;font-size:.85rem;margin-bottom:24px}
label{display:block;font-size:.75rem;color:#8b949e;margin-bottom:6px;text-transform:uppercase}
.drop{border:2px dashed #30363d;border-radius:8px;padding:36px;text-align:center;cursor:pointer;margin-bottom:18px;position:relative}
.drop:hover{border-color:#58a6ff;background:#161b22}
.drop input{position:absolute;inset:0;opacity:0;cursor:pointer;width:100%;height:100%}
.fname{color:#58a6ff;font-size:.85rem;margin-top:8px}
.modes{display:grid;grid-template-columns:repeat(2,1fr);gap:10px;margin-bottom:18px}
.mode{border:1px solid #30363d;border-radius:8px;padding:12px;cursor:pointer}
.mode:hover,.mode.sel{border-color:#58a6ff;background:#0d2137}
.mtitle{font-size:.9rem;font-weight:600;margin-bottom:3px}
.mdesc{font-size:.73rem;color:#8b949e;line-height:1.4}
.btn{width:100%;padding:13px;border:none;border-radius:8px;background:#238636;color:#fff;font-size:1rem;font-weight:600;cursor:pointer;margin-bottom:20px}
.btn:hover{background:#2ea043}
.btn:disabled{background:#21262d;color:#484f58;cursor:not-allowed}
.log{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:14px;font-family:monospace;font-size:.76rem;color:#8b949e;max-height:200px;overflow-y:auto;white-space:pre-wrap;word-break:break-all;margin-bottom:16px;display:none}
.res{background:#161b22;border:1px solid #238636;border-radius:8px;padding:14px;margin-bottom:16px;display:none}
.res h3{font-size:.85rem;color:#3fb950;margin-bottom:10px}
.res textarea{width:100%;height:300px;background:#0d1117;border:1px solid #30363d;border-radius:6px;color:#e6edf3;font-family:monospace;font-size:.76rem;padding:10px;resize:vertical}
.dl{margin-top:8px;padding:7px 16px;background:#1f6feb;border:none;border-radius:6px;color:#fff;font-size:.82rem;cursor:pointer}
.err{background:#2d1217;border:1px solid #f85149;border-radius:8px;padding:14px;font-family:monospace;font-size:.78rem;color:#f85149;white-space:pre-wrap;word-break:break-all;display:none;margin-bottom:16px}
.spin{display:inline-block;width:13px;height:13px;border:2px solid #fff3;border-top-color:#fff;border-radius:50%;animation:sp .7s linear infinite;vertical-align:middle;margin-right:7px}
@keyframes sp{to{transform:rotate(360deg)}}
</style>
</head>
<body>
<div class="container">
<h1>Luraph Deobfuscator</h1>
<p class="sub">v14.7 / v14.8 / v14.9</p>
<label>File</label>
<div class="drop" id="dz">
  <input type="file" id="fi" accept=".lua,.luau,.txt">
  <div id="dt" style="color:#8b949e;font-size:.9rem">Drop file or <span style="color:#58a6ff">click</span></div>
  <div class="fname" id="fn"></div>
</div>
<label>Mode</label>
<div class="modes">
  <div class="mode sel" data-m="normal" onclick="selMode(this)"><div class="mtitle">Normal</div><div class="mdesc">Full pipeline</div></div>
  <div class="mode" data-m="no-hooks" onclick="selMode(this)"><div class="mtitle">No Hooks</div><div class="mdesc">Skip VM instrumentation</div></div>
  <div class="mode" data-m="no-devirt" onclick="selMode(this)"><div class="mtitle">Trace Only</div><div class="mdesc">No devirt</div></div>
  <div class="mode" data-m="no-hooks-no-devirt" onclick="selMode(this)"><div class="mtitle">No Hooks + Trace</div><div class="mdesc">Max compat</div></div>
</div>
<button class="btn" id="rb" onclick="run()">Run</button>
<div class="log" id="log"></div>
<div class="err" id="err"></div>
<div class="res" id="res">
  <h3>Output</h3>
  <textarea id="out" readonly></textarea>
  <button class="dl" onclick="dl()">Download .lua</button>
</div>
</div>
<script>
let sf=null,sm="normal";
const fi=document.getElementById("fi"),fn=document.getElementById("fn"),dt=document.getElementById("dt");
const logEl=document.getElementById("log"),err=document.getElementById("err"),res=document.getElementById("res"),out=document.getElementById("out"),rb=document.getElementById("rb");
fi.addEventListener("change",()=>{if(fi.files[0])setFile(fi.files[0])});
document.getElementById("dz").addEventListener("dragover",e=>e.preventDefault());
document.getElementById("dz").addEventListener("drop",e=>{e.preventDefault();if(e.dataTransfer.files[0])setFile(e.dataTransfer.files[0])});
function setFile(f){sf=f;fn.textContent=f.name+" ("+(f.size/1024/1024).toFixed(2)+" MB)";dt.style.display="none"}
function selMode(c){document.querySelectorAll(".mode").forEach(x=>x.classList.remove("sel"));c.classList.add("sel");sm=c.dataset.m}
function addLog(m){logEl.style.display="block";logEl.textContent+=m+"\n";logEl.scrollTop=logEl.scrollHeight}
async function run(){
  if(!sf){alert("No file");return}
  logEl.style.display="none";logEl.textContent="";err.style.display="none";res.style.display="none";
  rb.disabled=true;rb.innerHTML="<span class=\"spin\"></span>Running...";
  addLog("[*] uploading "+sf.name);addLog("[*] mode: "+sm);
  const fd=new FormData();fd.append("file",sf);fd.append("mode",sm);
  try{
    const r=await fetch("/deobf",{method:"POST",body:fd});
    const d=await r.json();
    if(d.log)d.log.split("\n").forEach(l=>l&&addLog(l));
    if(d.error){err.style.display="block";err.textContent=d.error}
    else if(d.output){res.style.display="block";out.value=d.output;addLog("[+] done -- "+d.output.length+" chars")}
  }catch(e){err.style.display="block";err.textContent="Network error: "+e.message}
  finally{rb.disabled=false;rb.innerHTML="Run"}
}
function dl(){const b=new Blob([out.value],{type:"text/plain"});const a=document.createElement("a");a.href=URL.createObjectURL(b);a.download="deobfuscated.lua";a.click()}
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
        return jsonify({"error": "No file uploaded"}), 400
    mode = request.form.get("mode", "normal")
    log_lines = []
    def log(msg):
        log_lines.append(msg)
    workdir = None
    try:
        workdir = Path(tempfile.mkdtemp(prefix="luraph_web_"))
        inp = workdir / f.filename
        f.save(str(inp))
        source = read_source(inp)
        log(f"[*] file: {f.filename}  ({len(source)} chars)")
        version = detect_version(source)
        if version is None:
            return jsonify({"log": "\n".join(log_lines), "error": "[!] could not detect Luraph version"})
        log(f"[*] detected: Luraph v{version}")
        args = SimpleNamespace(
            input=str(inp), output=None,
            engine=version, engine_resolved=version,
            timeout=300.0, budget=120.0,
            executor="roblox", studio=False, input_text=None,
            no_hooks=(mode in ("no-hooks", "no-hooks-no-devirt")),
            no_devirt=(mode in ("no-devirt", "no-hooks-no-devirt")),
            max_runs=12, devirt_rounds=200,
            strings=False, raw=False, no_fold=False,
            keep_harness=False, no_tidy=False,
            keep_preamble=False, trace_fallback=True,
            debug=False, keep_work=False, no_credit=False,
            luau=None, bridge=None, cfg=[],
        )
        normalize_compat_args(args)
        log(f"[*] mode={mode} no_hooks={args.no_hooks} no_devirt={args.no_devirt}")
        out_path = workdir / "deobfuscated.lua"
        args.output = str(out_path)
        engine = load_engine(version)
        job_workdir = workdir / f".{inp.stem}_work"
        job_workdir.mkdir(exist_ok=True)
        job = Job(args, inp, source, job_workdir)
        log("[*] starting engine...")
        result_path_str = engine.deobfuscate(job)
        if not result_path_str:
            return jsonify({"log": "\n".join(log_lines), "error": "[!] engine returned no output"})
        result_path = Path(result_path_str)
        if not result_path.is_file():
            return jsonify({"log": "\n".join(log_lines), "error": f"[!] output not found: {result_path}"})
        output_text = result_path.read_text(encoding="latin-1", errors="replace")
        log(f"[+] output: {len(output_text)} chars")
        return jsonify({"log": "\n".join(log_lines), "output": output_text})
    except SystemExit as e:
        return jsonify({"log": "\n".join(log_lines), "error": str(e)})
    except Exception:
        return jsonify({"log": "\n".join(log_lines), "error": traceback.format_exc()})
    finally:
        if workdir and workdir.exists():
            try:
                shutil.rmtree(workdir)
            except Exception:
                pass

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
