"""Soldrin Smart Search API (FastAPI). Stateless, so it runs on Vercel serverless.

Flow: /api/details -> /api/parse (file -> rows) -> /api/embed (batched) -> /api/search.
The browser holds the index (texts + vectors) and sends it back with each search.
"""
from __future__ import annotations

import os
import re
import smtplib
import sys
import uuid
from email.message import EmailMessage
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


def notify(d: "Details") -> bool:
    """Email the visitor's details to NOTIFY_TO via SMTP (Outlook by default).

    Configure with env vars: SMTP_USER, SMTP_PASS (app password), NOTIFY_TO,
    optional SMTP_HOST (default smtp-mail.outlook.com) and SMTP_PORT (587).
    Never blocks the visitor: returns False if unconfigured or sending fails.
    """
    user, pwd, to = os.getenv("SMTP_USER"), os.getenv("SMTP_PASS"), os.getenv("NOTIFY_TO")
    if not (user and pwd and to):
        return False
    msg = EmailMessage()
    msg["Subject"] = f"New Smart Search visitor: {d.firstName}"
    msg["From"], msg["To"] = user, to
    msg.set_content(f"Name: {d.firstName}\nMobile: {d.mobile}")
    try:
        with smtplib.SMTP(os.getenv("SMTP_HOST", "smtp-mail.outlook.com"), int(os.getenv("SMTP_PORT", "587")), timeout=8) as s:
            s.starttls()
            s.login(user, pwd)
            s.send_message(msg)
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"notify failed: {exc}")
        return False


@app.get("/api/health")
def health():
    return {"status": "ok", "model": engine.MODEL_NAME}


@app.post("/api/details", status_code=201)
def details(d: Details):
    notify(d)
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
