"""Local upload interface for the Secret Wards pipeline."""
import io
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
from zipfile import ZipFile, ZIP_DEFLATED

from flask import Flask, render_template, request, send_file

HERE = Path(__file__).resolve().parent
app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 64 * 1024 * 1024


@app.get("/")
def home():
    return render_template("index.html")


@app.post("/process")
def process():
    uploads = request.files.getlist("files")
    if not uploads or not any(f.filename for f in uploads):
        return {"error": "Choose at least one file."}, 400
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        source = root / "input"
        source.mkdir()
        out = root / "release"
        for index, upload in enumerate(uploads):
            # Isolate duplicate names and strip client-provided directories.
            name = (upload.filename or "").replace("\\", "/").rsplit("/", 1)[-1]
            if not name or Path(name).is_reserved() or any(ord(c)<32 or c in '<>:"|?*' for c in name) or name.endswith((".", " ")):
                return {"error": "A filename is invalid. Rename the file and try again."}, 400
            folder = source / f"batch_{index+1}"
            folder.mkdir()
            upload.save(folder / name)
        try:
            subprocess.run(
                [sys.executable, str(HERE.parent / "main.py"), "--input", str(source), "--output", str(out)],
                env={**os.environ, "RAKSHA_SECRET": secrets.token_hex(32)},
                check=True, capture_output=True, timeout=900,
            )
        except (subprocess.SubprocessError, OSError):
            return {"error": "Processing failed. No release was created."}, 422
        report = json.loads((out / "report.json").read_bytes())
        archive = io.BytesIO()
        with ZipFile(archive, "w", ZIP_DEFLATED) as bundle:
            for path in sorted(out.rglob("*")):
                if path.is_file():
                    bundle.write(path, path.relative_to(out))
        archive.seek(0)
        response = send_file(archive, as_attachment=True, download_name="secret-wards-release.zip",
                             mimetype="application/zip", max_age=0)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Run-Counts"] = json.dumps(report["counts"])
        response.headers["X-Quarantine-Reasons"] = json.dumps(sorted({
            f.get("reason", "unknown") for f in report["files"] if f["status"] == "quarantined"
        }))
        return response


@app.errorhandler(413)
def too_large(error):
    return {"error": "This batch exceeds 64 MiB. Try fewer or smaller files."}, 413


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5057, debug=False)
