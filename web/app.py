from __future__ import annotations

import os
import hmac
import re
import subprocess
import sys
import tempfile
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from flask import Flask, Response, abort, jsonify, render_template, request, send_file
from werkzeug.utils import secure_filename

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUN_ROOT = Path(tempfile.gettempdir()) / "novo_aprovadores_web"
MAX_UPLOAD_BYTES = 100 * 1024 * 1024
ALLOWED_EXTENSIONS = {".xlsx", ".xlsm"}

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_BYTES
app.config["TEMPLATES_AUTO_RELOAD"] = True
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0

_jobs: dict[str, dict[str, Any]] = {}
_jobs_lock = threading.Lock()
_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="aprovadores")


def _valid_run_id(run_id: str) -> bool:
    return bool(re.fullmatch(r"[0-9a-f]{32}", run_id))


def _append_log(job: dict[str, Any], message: str) -> None:
    with _jobs_lock:
        job["log"].append(message.rstrip())
        job["log"] = job["log"][-500:]


def _execute_job(run_id: str, job: dict[str, Any], arguments: list[str], run_dir: Path) -> None:
    with _jobs_lock:
        job["status"] = "running"
        job["message"] = "Lendo planilhas e calculando aprovadores"

    command = [sys.executable, "-m", "src.main", *arguments]
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(PROJECT_ROOT)
    environment["PYTHONIOENCODING"] = "utf-8"

    try:
        process = subprocess.Popen(
            command,
            cwd=run_dir,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        with _jobs_lock:
            job["process"] = process

        assert process.stdout is not None
        for line in process.stdout:
            _append_log(job, line)
            if "Processados " in line:
                with _jobs_lock:
                    job["message"] = line.strip()

        return_code = process.wait()
        with _jobs_lock:
            job["process"] = None
            job["return_code"] = return_code
            if return_code == 0:
                job["status"] = "completed"
                job["message"] = "Arquivos prontos para baixar"
                job["artifacts"] = {
                    "auditoria": "auditoria.xlsx",
                    "belvitur": "belvitur_atualizada.xlsx",
                }
            else:
                job["status"] = "failed"
                job["message"] = "O processamento terminou com erro. Consulte o log."
    except Exception as error:
        with _jobs_lock:
            job["process"] = None
            job["status"] = "failed"
            job["message"] = f"Não foi possível iniciar o processamento: {error}"
        _append_log(job, str(error))


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/health")
def health():
    return jsonify(status="ok")


@app.before_request
def require_deploy_authentication():
    if os.environ.get("APP_ENV") != "production" or request.endpoint == "health":
        return None

    username = os.environ.get("WEB_USERNAME", "")
    password = os.environ.get("WEB_PASSWORD", "")
    credentials = request.authorization
    if (
        not username
        or not password
        or credentials is None
        or credentials.type.lower() != "basic"
        or not hmac.compare_digest(credentials.username or "", username)
        or not hmac.compare_digest(credentials.password or "", password)
    ):
        return Response(
            "Autenticação necessária.",
            401,
            {"WWW-Authenticate": 'Basic realm="Aprovadores", charset="UTF-8"'},
        )
    return None


@app.post("/api/runs")
def create_run():
    required = ("sap", "depara", "belvitur")
    missing = [name for name in required if name not in request.files or not request.files[name].filename]
    if missing:
        return jsonify(error=f"Selecione os arquivos obrigatórios: {', '.join(missing)}."), 400

    update_depara = request.form.get("atualizar_depara") == "true"
    rh_file = request.files.get("rh")
    has_rh = rh_file is not None and bool(rh_file.filename)
    if update_depara and not has_rh:
        return jsonify(error="Para atualizar o DePara, selecione também a base RH."), 400

    uploaded = {name: request.files[name] for name in required}
    if has_rh:
        uploaded["rh"] = rh_file

    for field, file in uploaded.items():
        suffix = Path(file.filename or "").suffix.lower()
        if suffix not in ALLOWED_EXTENSIONS:
            return jsonify(error=f"O arquivo {field} deve estar no formato .xlsx ou .xlsm."), 400

    run_id = uuid.uuid4().hex
    run_dir = RUN_ROOT / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    saved: dict[str, Path] = {}
    for field, file in uploaded.items():
        safe_name = secure_filename(Path(file.filename or field).name) or f"{field}.xlsx"
        destination = run_dir / f"{field}_{safe_name}"
        file.save(destination)
        saved[field] = destination

    audit_path = run_dir / "auditoria.xlsx"
    belvitur_path = run_dir / "belvitur_atualizada.xlsx"
    arguments = [
        "--sap", str(saved["sap"]),
        "--depara", str(saved["depara"]),
        "--saida", str(audit_path),
        "--belvitur", str(saved["belvitur"]),
        "--saida-belvitur", str(belvitur_path),
    ]
    if has_rh:
        arguments.extend(["--rh", str(saved["rh"])])
    if update_depara:
        arguments.append("--atualizar-depara")

    job: dict[str, Any] = {
        "id": run_id,
        "status": "queued",
        "message": "Na fila de processamento",
        "log": [],
        "process": None,
        "return_code": None,
        "artifacts": {},
        "run_dir": run_dir,
    }
    with _jobs_lock:
        _jobs[run_id] = job
    _executor.submit(_execute_job, run_id, job, arguments, run_dir)
    return jsonify(id=run_id, status=job["status"]), 202


@app.get("/api/runs/<run_id>")
def run_status(run_id: str):
    if not _valid_run_id(run_id):
        abort(404)
    with _jobs_lock:
        job = _jobs.get(run_id)
        if job is None:
            abort(404)
        return jsonify(
            id=job["id"],
            status=job["status"],
            message=job["message"],
            log=job["log"],
            artifacts=job["artifacts"],
        )


@app.get("/api/runs/<run_id>/files/<kind>")
def download_file(run_id: str, kind: str):
    if not _valid_run_id(run_id):
        abort(404)
    filenames = {"auditoria": "auditoria.xlsx", "belvitur": "belvitur_atualizada.xlsx"}
    if kind not in filenames:
        abort(404)
    with _jobs_lock:
        job = _jobs.get(run_id)
        if job is None or job["status"] != "completed":
            abort(404)
        path = Path(job["run_dir"]) / filenames[kind]
    if not path.is_file():
        abort(404)
    return send_file(path, as_attachment=True, download_name=filenames[kind])


@app.errorhandler(413)
def too_large(_error):
    return jsonify(error="O total enviado ultrapassa o limite de 100 MB."), 413


if __name__ == "__main__":
    RUN_ROOT.mkdir(parents=True, exist_ok=True)
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", "5055")), debug=False, threaded=True)
