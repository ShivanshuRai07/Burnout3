"""
Serve the BurnoutIQ frontend and forward /api/* to the running dashboard server.

The frontend computes nothing itself: every number comes from the loop via the existing API.
It also serves the three input templates and checks uploaded CSVs with burnoutiq.schema.validate.

  python dashboard_server.py --port 8501        # terminal 1: the model + loop API
  python frontend/serve.py --port 8600          # terminal 2: this frontend
  open http://127.0.0.1:8600
"""
import argparse
import io
import json
import mimetypes
import sys
import urllib.error
import urllib.request
from email import policy
from email.parser import BytesParser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
STATIC = {"index.html", "styles.css", "app.js"}
TEMPLATES = {"employees_template.csv", "monthly_template.csv", "interventions_template.csv",
             # a ready-made 400-person company to try the upload with
             "sample_company/employees.csv", "sample_company/monthly.csv", "sample_company/interventions.csv",
             # December 2025 for the demo, uploaded by hand after signing in
             "demo/monthly_2025-12.csv"}
MAX_UPLOAD = 50 * 1024 * 1024
STAGE_ORDER = ["Assess", "Predict", "Simulate", "Intervene", "Verify", "Learn"]


def check_files(files: dict) -> dict:
    """Validate the three input CSVs with the model package's own schema rules.

    Adoption level follows burnoutiq/schema.py: CBI items only = level 1 (Assess, Verify);
    any work-data column filled = level 2 (adds Predict, Simulate).
    """
    import pandas as pd
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from burnoutiq import schema

    try:
        frames = {k: pd.read_csv(io.BytesIO(v)) for k, v in files.items() if v}
    except Exception as e:  # unreadable CSV
        return {"ok": False, "error": f"Could not read a file as CSV: {e}"}
    if "employees" not in frames or "monthly" not in frames:
        return {"ok": False, "error": "employees.csv and monthly.csv are required."}
    try:
        inputs = schema.validate(frames["employees"], frames["monthly"], frames.get("interventions"))
    except schema.InputError as e:
        return {"ok": False, "error": str(e)}

    m = inputs.monthly
    work = [c for c in schema.MONTHLY_OPTIONAL if c in m.columns and m[c].notna().any()]
    level = 2 if work else 1
    stages = {"Assess", "Verify"} | ({"Predict", "Simulate"} if level == 2 else set())
    if len(inputs.interventions):
        stages |= {"Intervene", "Learn"}
    periods = sorted(m["period"].dropna().astype(str).unique()) if "period" in m else []
    return {
        "ok": True, "level": level, "work_columns": work,
        "stages": [s for s in STAGE_ORDER if s in stages],
        "issues": list(inputs.issues),
        "counts": {"employees": len(inputs.employees), "monthly": len(m), "interventions": len(inputs.interventions)},
        "periods": [periods[0], periods[-1]] if periods else [],
    }


def parse_multipart(content_type: str, body: bytes) -> dict:
    msg = BytesParser(policy=policy.default).parsebytes(
        b"Content-Type: " + content_type.encode() + b"\r\nMIME-Version: 1.0\r\n\r\n" + body)
    out = {}
    for part in msg.iter_parts():
        name = part.get_param("name", header="content-disposition")
        if name:
            out[name] = part.get_payload(decode=True) or b""
    return out


class Handler(BaseHTTPRequestHandler):
    api = "http://127.0.0.1:8501"

    def log_message(self, fmt, *args):
        pass

    def _send(self, status, body, ctype):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _proxy(self, method):
        length = int(self.headers.get("Content-Length") or 0)
        data = self.rfile.read(length) if length else None
        req = urllib.request.Request(self.api + self.path, data=data, method=method)
        if self.headers.get("Content-Type"):
            req.add_header("Content-Type", self.headers["Content-Type"])
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                self._send(r.status, r.read(), r.headers.get("Content-Type", "application/json"))
        except urllib.error.HTTPError as e:
            self._send(e.code, e.read(), e.headers.get("Content-Type", "application/json"))
        except (urllib.error.URLError, TimeoutError):
            msg = b'{"error": "The model API is not running. Start: python dashboard_server.py --port 8501"}'
            self._send(HTTPStatus.BAD_GATEWAY, msg, "application/json")

    def do_GET(self):
        if self.path.startswith("/api/"):
            return self._proxy("GET")
        name = self.path.split("?")[0].lstrip("/") or "index.html"
        if name.startswith("templates/") and name.split("/", 1)[1] in TEMPLATES:
            return self._send(HTTPStatus.OK, (ROOT / name).read_bytes(), "text/csv; charset=utf-8")
        if name not in STATIC:
            return self._send(HTTPStatus.NOT_FOUND, b"not found", "text/plain")
        ctype = mimetypes.guess_type(name)[0] or "application/octet-stream"
        self._send(HTTPStatus.OK, (HERE / name).read_bytes(), f"{ctype}; charset=utf-8")

    def do_POST(self):
        if self.path.startswith("/api/"):
            return self._proxy("POST")
        if self.path == "/data/check":
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_UPLOAD:
                result = {"ok": False, "error": "Files are larger than 50 MB in total."}
            else:
                files = parse_multipart(self.headers.get("Content-Type", ""), self.rfile.read(length))
                result = check_files(files)
            return self._send(HTTPStatus.OK, json.dumps(result).encode(), "application/json")
        self._send(HTTPStatus.METHOD_NOT_ALLOWED, b"", "text/plain")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8600)
    ap.add_argument("--api", default="http://127.0.0.1:8501", help="base URL of dashboard_server.py")
    a = ap.parse_args()
    Handler.api = a.api.rstrip("/")
    print(f"BurnoutIQ frontend on http://127.0.0.1:{a.port}  (API: {Handler.api})")
    ThreadingHTTPServer(("127.0.0.1", a.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
