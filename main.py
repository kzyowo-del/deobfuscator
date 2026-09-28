from flask import Flask, request, jsonify
import subprocess, tempfile, os

app = Flask(__name__)
DEOBF_PATH = "/app/Deobfuscator/deobf"

@app.route("/")
def index():
    return "deobfuscator online", 200

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
             "--timeout", "120", "--trace-fallback"],
            cwd=DEOBF_PATH,
            capture_output=True, text=True, timeout=180
        )
        if os.path.exists(output_path):
            with open(output_path) as out:
                return jsonify({"result": out.read(), "log": result.stderr})
        else:
            return jsonify({"error": "failed", "log": result.stderr}), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
