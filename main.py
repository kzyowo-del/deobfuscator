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

HTML = open(os.path.join(os.path.dirname(__file__), "templates", "index.html")).read() if os.path.exists(os.path.join(os.path.dirname(__file__), "templates", "index.html")) else "<h1>UI missing</h1>"

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
