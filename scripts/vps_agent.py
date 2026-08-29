"""
VPS agent — минимальный HTTP-мост для удалённого управления сервером weather-odessa-vps
через HTTPS вместо SSH (см. docs/topics/hosting_migration.md).

Эндпоинты (все, кроме /health, требуют токен — заголовок Authorization: Bearer <TOKEN>
ЛИБО query-параметр ?token=<TOKEN> для /snapshot, чтобы можно было открыть ссылку прямо
в браузере телефона без ручного проставления заголовков):
  GET  /health                — без авторизации, просто проверка что сервис жив
  GET  /snapshot?token=..&format=text|html — полный снимок состояния сервера одной ссылкой
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
import html
import os
import subprocess
import time
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse, PlainTextResponse
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


def _check_auth_flexible(authorization: Optional[str], token_qs: Optional[str]) -> None:
    """Тот же контроль доступа, но допускает токен как query-параметр (?token=..),
    чтобы ссылку можно было просто открыть в браузере/curl без заголовков."""
    if token_qs and token_qs == TOKEN:
        return
    _check_auth(authorization)


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


SNAPSHOT_SECTIONS = [
    ("DISK", "df -h /"),
    ("DU /opt", "du -sh /opt/* 2>/dev/null"),
    ("DU /var/log", "du -sh /var/log 2>/dev/null"),
    ("MEMORY", "free -h"),
    ("NETWORK", "ip -brief addr show"),
    ("CRON", "sudo crontab -l 2>/dev/null"),
    ("SERVICES", "systemctl is-active vps-agent caddy 2>&1 | paste -sd ' '"),
    ("REPO (top level)", "ls -la /opt/weather-pipeline/repo 2>/dev/null | head -20"),
    ("VPS-PIPELINE LOG (tail)", "tail -25 /var/log/vps-pipeline.log 2>/dev/null"),
    ("GITHUB-BRIDGE LOG (tail)", "tail -15 /var/log/vps-github-bridge.log 2>/dev/null"),
    ("UPTIME / LOAD", "uptime"),
    (
        "ALWAYS FREE LIMITS (справочно, не запрос к Oracle API)",
        "echo 'Тариф: Oracle Cloud Always Free — оплата не взимается, пока не превышены лимиты.'; "
        "echo 'Shape: VM.Standard.A1.Flex, лимит аккаунта: <=2 OCPU / <=12GB RAM суммарно.'; "
        "echo 'Boot+block volume: <=200GB суммарно на аккаунт.'; "
        "echo 'Проверка фактического биллинга/остатка триал-кредита требует OCI CLI/API ключи'; "
        "echo '(они есть в GitHub Secrets для oci_capacity_retry.py, на самом VPS не хранятся —'; "
        "echo 'сознательно, чтобы не расширять поверхность утечки на интернет-смотрящем сервере).'",
    ),
]


def _collect_snapshot() -> str:
    parts = []
    for title, cmd in SNAPSHOT_SECTIONS:
        try:
            result = subprocess.run(
                cmd, shell=True, capture_output=True, text=True, timeout=20
            )
            output = (result.stdout or "").rstrip()
            if result.stderr and not output:
                output = f"(stderr) {result.stderr.strip()}"
            if not output:
                output = "(пусто)"
        except subprocess.TimeoutExpired:
            output = "(таймаут)"
        parts.append(f"=== {title} ===\n{output}")
    ts = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())
    header = f"weather-odessa-vps snapshot — {ts}"
    return header + "\n\n" + "\n\n".join(parts) + "\n"


@app.get("/snapshot")
def snapshot(
    authorization: Optional[str] = Header(None),
    token: Optional[str] = None,
    format: str = "text",
):
    _check_auth_flexible(authorization, token)
    text = _collect_snapshot()
    if format == "html":
        escaped = html.escape(text)
        page = f"""<!DOCTYPE html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>weather-odessa-vps snapshot</title>
<style>
  body {{ background:#0d1117; color:#c9d1d9; font-family: ui-monospace, monospace;
          margin:0; padding:16px; }}
  pre {{ white-space: pre-wrap; word-break: break-word; font-size: 13px; line-height:1.4; }}
</style></head>
<body><pre>{escaped}</pre></body></html>"""
        return HTMLResponse(content=page)
    return PlainTextResponse(content=text)


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
