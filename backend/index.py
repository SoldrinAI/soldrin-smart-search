"""Soldrin Smart Search API (FastAPI). Stateless, so it runs on Vercel serverless.

Flow: /api/details -> /api/parse (file -> rows) -> /api/embed (batched) -> /api/search.
The browser holds the index (texts + vectors) and sends it back with each search.
"""
from __future__ import annotations

import base64
import csv
import io
import json
import os
import re
import sys
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from pydantic import BaseModel, Field, field_validator

sys.path.insert(0, str(Path(__file__).parent))  # sibling imports on Vercel

import engine  # noqa: E402
import files  # noqa: E402

MAX_UPLOAD = 4 * 1024 * 1024  # Vercel request bodies are capped at ~4.5 MB

app = FastAPI(title="Soldrin Smart Search API", docs_url="/api/docs", openapi_url="/api/openapi.json")


class Details(BaseModel):
    firstName: str = Field(min_length=1, max_length=80)
    mobile: str = Field(min_length=7, max_length=20)

    @field_validator("mobile")
    @classmethod
    def _mobile(cls, v: str) -> str:
        v = v.strip()
        if not re.fullmatch(r"[0-9+()\-\s]{7,20}", v):
            raise ValueError("Enter a valid mobile number.")
        return v

    @field_validator("firstName")
    @classmethod
    def _name(cls, v: str) -> str:
        v = " ".join(v.split())
        if not v:
            raise ValueError("First name is required.")
        return v


class EmbedIn(BaseModel):
    texts: list[str] = Field(min_length=1, max_length=128)


class SearchIn(BaseModel):
    query: str = Field(min_length=2, max_length=500)
    texts: list[str] = Field(min_length=1, max_length=files.MAX_ROWS)
    vectors: list[str]
    limit: int = Field(default=20, ge=1, le=50)


def log_visitor(d: "Details") -> bool:
    """Append "timestamp,name,mobile" to a CSV in a (private!) GitHub repo via the contents API.

    Env vars: LOG_TOKEN (fine-grained PAT, Contents: read & write on that repo only),
    LOG_REPO ("owner/repo"), optional LOG_PATH (default leads.csv), LOG_BRANCH (default repo default).
    Never blocks the visitor: returns False if unconfigured or the write fails.
    """
    token, repo = os.getenv("LOG_TOKEN"), os.getenv("LOG_REPO")
    if not (token and repo):
        return False
    path, branch = os.getenv("LOG_PATH", "leads.csv"), os.getenv("LOG_BRANCH")
    url = f"https://api.github.com/repos/{repo}/contents/{path}"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
               "User-Agent": "soldrin-smart-search", "X-GitHub-Api-Version": "2022-11-28"}
    safe = lambda v: "'" + v if v[:1] in "=+-@" else v  # noqa: E731  (CSV formula injection)
    buf = io.StringIO()
    csv.writer(buf).writerow([datetime.now(timezone.utc).isoformat(timespec="seconds"), safe(d.firstName), safe(d.mobile)])
    row = buf.getvalue()

    def call(method: str, data: dict | None = None, query: str = ""):
        req = urllib.request.Request(url + query, method=method, headers=headers,
                                     data=json.dumps(data).encode() if data else None)
        with urllib.request.urlopen(req, timeout=8) as r:
            return json.loads(r.read())

    q = f"?ref={branch}" if branch else ""
    for _ in range(4):  # retry if two visitors write at the same moment
        try:
            try:
                cur = call("GET", query=q)
                text, sha = base64.b64decode(cur["content"]).decode(), cur["sha"]
            except urllib.error.HTTPError as e:
                if e.code != 404:
                    raise
                text, sha = "timestamp_utc,first_name,mobile\n", None
            body = {"message": "Log new visitor", "content": base64.b64encode((text + row).encode()).decode()}
            if sha:
                body["sha"] = sha
            if branch:
                body["branch"] = branch
            call("PUT", body)
            return True
        except urllib.error.HTTPError as e:
            if e.code not in (409, 422):
                print(f"visitor log failed: {e.code}")
                return False
        except Exception as exc:  # noqa: BLE001
            print(f"visitor log failed: {exc}")
            return False
    return False


@app.get("/api/health")
def health():
    return {"status": "ok", "model": engine.MODEL_NAME}


@app.post("/api/details", status_code=201)
def details(d: Details):
    log_visitor(d)
    return {"sessionId": str(uuid.uuid4()), "firstName": d.firstName, "mobile": d.mobile}


@app.post("/api/parse")
async def parse(file: UploadFile = File(...)):
    content = await file.read()
    if len(content) > MAX_UPLOAD:
        raise HTTPException(413, "File is too large. Keep uploads under 4 MB.")
    return files.parse(file.filename or "dataset", content)


@app.post("/api/embed")
def embed(body: EmbedIn):
    return {"vectors": engine.encode_vectors(engine.embed(body.texts)), "count": len(body.texts)}


@app.post("/api/search")
def search(body: SearchIn):
    vectors = engine.decode_vectors(body.vectors)
    if len(vectors) != len(body.texts):
        raise HTTPException(400, "Index is incomplete. Re-index the file.")
    hits = engine.hybrid_search(body.query, body.texts, vectors, body.limit)
    return {"query": body.query, "totalRows": len(body.texts), "results": hits,
            "method": f"{int(engine.VECTOR_WEIGHT * 100)}% semantic + {100 - int(engine.VECTOR_WEIGHT * 100)}% keyword",
            "model": engine.MODEL_NAME}
