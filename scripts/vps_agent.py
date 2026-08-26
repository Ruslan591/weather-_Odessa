"""
VPS agent — минимальный HTTP-мост для удалённого управления сервером weather-odessa-vps
через HTTPS вместо SSH (см. docs/topics/hosting_migration.md).

Эндпоинты (все, кроме /health, требуют заголовок Authorization: Bearer <TOKEN>):
  GET  /health                — без авторизации, просто проверка что сервис жив
  POST /exec   {"cmd": "..."}       — выполнить shell-команду, вернуть stdout/stderr/returncode
  POST /read   {"path": "..."}      — прочитать текстовый файл
  POST /write  {"path": "...", "content": "..."} — записать файл (создаёт директории)
  POST /upload {"path": "...", "content_b64": "..."} — записать бинарный файл (base64)

Токен читается из переменной окружения VPS_AGENT_TOKEN (устанавливается install-скриптом,
хранится в /etc/vps-agent/token, systemd EnvironmentFile).

Сервис слушает только на 127.0.0.1:8080 — наружу торчит через Caddy (автоматический
Let's Encrypt TLS + reverse proxy), см. Caddyfile в этом же коммите.
"""

import base64
import os
import subprocess
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

app = FastAPI(title="weather-odessa-vps-agent")

TOKEN = os.environ.get("VPS_AGENT_TOKEN", "")
if not TOKEN:
    raise RuntimeError("VPS_AGENT_TOKEN не задан в окружении — агент отказывается стартовать")

EXEC_TIMEOUT_SECONDS = 120


def _check_auth(authorization: Optional[str]) -> None:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    provided = authorization.removeprefix("Bearer ").strip()
    if provided != TOKEN:
        raise HTTPException(status_code=403, detail="invalid token")


class ExecRequest(BaseModel):
    cmd: str
    timeout: Optional[int] = None
    cwd: Optional[str] = None


class ReadRequest(BaseModel):
    path: str
    max_bytes: Optional[int] = 200_000


class WriteRequest(BaseModel):
    path: str
    content: str
    append: Optional[bool] = False


class UploadRequest(BaseModel):
    path: str
    content_b64: str


@app.get("/health")
def health():
    return {"status": "ok", "service": "weather-odessa-vps-agent"}


@app.post("/exec")
def exec_cmd(req: ExecRequest, authorization: Optional[str] = Header(None)):
    _check_auth(authorization)
    timeout = req.timeout or EXEC_TIMEOUT_SECONDS
    try:
        result = subprocess.run(
            req.cmd,
            shell=True,
            cwd=req.cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return {
            "returncode": result.returncode,
            "stdout": result.stdout[-100_000:],
            "stderr": result.stderr[-100_000:],
        }
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail=f"command timed out after {timeout}s")


@app.post("/read")
def read_file(req: ReadRequest, authorization: Optional[str] = Header(None)):
    _check_auth(authorization)
    p = Path(req.path)
    if not p.is_file():
        raise HTTPException(status_code=404, detail="file not found")
    data = p.read_bytes()[: req.max_bytes or 200_000]
    try:
        return {"path": str(p), "content": data.decode("utf-8"), "truncated": p.stat().st_size > len(data)}
    except UnicodeDecodeError:
        return {
            "path": str(p),
            "content_b64": base64.b64encode(data).decode("ascii"),
            "encoding": "base64",
            "truncated": p.stat().st_size > len(data),
        }


@app.post("/write")
def write_file(req: WriteRequest, authorization: Optional[str] = Header(None)):
    _check_auth(authorization)
    p = Path(req.path)
    p.parent.mkdir(parents=True, exist_ok=True)
    mode = "a" if req.append else "w"
    with open(p, mode, encoding="utf-8") as f:
        f.write(req.content)
    return {"path": str(p), "bytes_written": len(req.content.encode("utf-8")), "append": bool(req.append)}


@app.post("/upload")
def upload_file(req: UploadRequest, authorization: Optional[str] = Header(None)):
    _check_auth(authorization)
    p = Path(req.path)
    p.parent.mkdir(parents=True, exist_ok=True)
    data = base64.b64decode(req.content_b64)
    p.write_bytes(data)
    return {"path": str(p), "bytes_written": len(data)}
