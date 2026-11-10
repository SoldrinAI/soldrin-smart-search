"""Embedding + hybrid ranking engine (no torch: ONNX Runtime keeps the bundle tiny).

Model: sentence-transformers/all-MiniLM-L6-v2, int8-quantised ONNX (~23 MB, 384-d).
"""
from __future__ import annotations

import base64
import math
import re
from functools import lru_cache
from pathlib import Path

import numpy as np
import onnxruntime as ort
from tokenizers import Tokenizer

MODEL_NAME = "all-MiniLM-L6-v2 (ONNX int8)"
MODEL_DIR = Path(__file__).parent / "model"
MAX_TOKENS = 128
DIM = 384
VECTOR_WEIGHT = 0.65
TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")


@lru_cache(maxsize=1)
def _load():
    tok = Tokenizer.from_file(str(MODEL_DIR / "tokenizer.json"))
    tok.no_padding()
    tok.enable_truncation(MAX_TOKENS)
    opts = ort.SessionOptions()
    opts.log_severity_level = 3
    sess = ort.InferenceSession(str(MODEL_DIR / "model.onnx"), opts, providers=["CPUExecutionProvider"])
    return tok, sess, {i.name for i in sess.get_inputs()}


def embed(texts: list[str], batch: int = 32) -> np.ndarray:
    """Return L2-normalised sentence embeddings, shape (n, 384), float32."""
    tok, sess, names = _load()
    out = []
    for start in range(0, len(texts), batch):
        encs = tok.encode_batch(texts[start:start + batch])
        width = max(len(e.ids) for e in encs) or 1
        ids = np.zeros((len(encs), width), dtype=np.int64)
        mask = np.zeros_like(ids)
        for i, e in enumerate(encs):
            ids[i, :len(e.ids)] = e.ids
            mask[i, :len(e.ids)] = 1
        feed = {"input_ids": ids, "attention_mask": mask, "token_type_ids": np.zeros_like(ids)}
        hidden = sess.run(None, {k: v for k, v in feed.items() if k in names})[0]
        m = mask[..., None].astype(np.float32)
        pooled = (hidden * m).sum(1) / np.clip(m.sum(1), 1e-9, None)  # mean pooling
        out.append(pooled / np.clip(np.linalg.norm(pooled, axis=1, keepdims=True), 1e-9, None))
    return np.vstack(out).astype(np.float32) if out else np.zeros((0, DIM), np.float32)


def encode_vectors(v: np.ndarray) -> str:
    return base64.b64encode(v.astype(np.float16).tobytes()).decode()


def decode_vectors(chunks: list[str]) -> np.ndarray:
    raw = b"".join(base64.b64decode(c) for c in chunks)
    return np.frombuffer(raw, dtype=np.float16).astype(np.float32).reshape(-1, DIM)


def tokenize(text: str) -> list[str]:
    return [m.group(0).lower() for m in TOKEN_RE.finditer(text)]


def bm25(docs: list[list[str]], query: list[str]) -> np.ndarray:
    n = len(docs)
    scores = np.zeros(n, dtype=np.float32)
    if not n or not query:
        return scores
    avg = sum(len(d) for d in docs) / n or 1
    df: dict[str, int] = {}
    for d in docs:
        for t in set(d):
            df[t] = df.get(t, 0) + 1
    for i, d in enumerate(docs):
        counts: dict[str, int] = {}
        for t in d:
            counts[t] = counts.get(t, 0) + 1
        for t in query:
            if t in counts:
                idf = math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5))
                scores[i] += idf * counts[t] * 2.2 / (counts[t] + 1.2 * (0.25 + 0.75 * len(d) / avg))
    return scores


def _norm(x: np.ndarray) -> np.ndarray:
    if not x.size:
        return x
    lo, hi = float(x.min()), float(x.max())
    if math.isclose(lo, hi):
        return np.full_like(x, 1.0 if hi > 0 else 0.0)
    return (x - lo) / (hi - lo)


def hybrid_search(query: str, texts: list[str], vectors: np.ndarray, limit: int) -> list[dict]:
    qv = embed([query])[0]
    vec = _norm(np.clip(vectors @ qv, 0, None))
    lex = _norm(bm25([tokenize(t) for t in texts], tokenize(query)))
    score = VECTOR_WEIGHT * vec + (1 - VECTOR_WEIGHT) * lex
    order = np.argsort(-score)[:limit]
    return [
        {"index": int(i), "score": round(float(score[i]), 6),
         "vectorScore": round(float(vec[i]), 6), "bm25Score": round(float(lex[i]), 6)}
        for i in order
    ]
