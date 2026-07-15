from __future__ import annotations

import base64
import binascii
import hmac
import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.requests import Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from open_novel import __version__

app = FastAPI(title="Open Novel", version=__version__)
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"https?://(127\.0\.0\.1|localhost)(:\d+)?",
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _request_has_access_token(request: Request, expected: str) -> bool:
    authorization = request.headers.get("authorization", "")
    scheme, _, credentials = authorization.partition(" ")
    if scheme.lower() == "bearer":
        return hmac.compare_digest(credentials.strip(), expected)
    if scheme.lower() == "basic":
        try:
            decoded = base64.b64decode(credentials, validate=True).decode("utf-8")
        except (binascii.Error, UnicodeDecodeError):
            return False
        _, separator, password = decoded.partition(":")
        return bool(separator) and hmac.compare_digest(password, expected)
    header_token = request.headers.get("x-open-novel-token", "")
    return bool(header_token) and hmac.compare_digest(header_token, expected)


@app.middleware("http")
async def require_optional_access_token(request: Request, call_next):
    expected = os.environ.get("OPEN_NOVEL_ACCESS_TOKEN", "").strip()
    if not expected or request.url.path == "/health":
        return await call_next(request)
    if _request_has_access_token(request, expected):
        return await call_next(request)
    return JSONResponse(
        status_code=401,
        content={"detail": "需要提供 Open Novel 访问令牌。"},
        headers={"WWW-Authenticate": 'Basic realm="Open Novel", charset="UTF-8"'},
    )


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "version": __version__}


def mount_static_if_configured(static_dir: str) -> None:
    if not static_dir or not Path(static_dir).is_dir():
        return
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")
