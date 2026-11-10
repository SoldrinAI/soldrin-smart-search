import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import engine  # noqa: E402
import files  # noqa: E402
from index import app  # noqa: E402

client = TestClient(app)
CSV = b"Name,Role,Notes\nAna,Veterinarian,Treats dogs and cats\nRaj,Mechanic,Repairs car engines\nLena,Chef,Cooks Italian pasta\n"


def test_parse_csv_rows_and_text():
    out = files.parse("x.csv", CSV)
    assert out["rowCount"] == 3 and out["columns"] == ["Name", "Role", "Notes"]
    assert "Role: Veterinarian" in out["texts"][0]


def test_parse_rejects_bad_files():
    with pytest.raises(Exception):
        files.parse("x.txt", b"hi")
    with pytest.raises(Exception):
        files.parse("x.csv", b"Name,Role\n")


def test_embeddings_are_normalised_384d():
    v = engine.embed(["hello world", "another sentence"])
    assert v.shape == (2, 384)
    assert abs(float((v[0] ** 2).sum()) - 1) < 1e-3


def test_vector_roundtrip_float16():
    v = engine.embed(["round trip"])
    back = engine.decode_vectors([engine.encode_vectors(v)])
    assert (back * v).sum() > 0.999


def test_semantic_search_finds_meaning_not_words():
    texts = ["Role: Veterinarian | Notes: Treats dogs and cats", "Role: Mechanic | Notes: Repairs car engines"]
    hits = engine.hybrid_search("animal doctor", texts, engine.embed(texts), 2)
    assert hits[0]["index"] == 0


def test_keyword_match_still_wins_for_exact_terms():
    texts = ["Name: Lena | Country: Italy", "Name: Omar | Country: UAE"]
    hits = engine.hybrid_search("UAE", texts, engine.embed(texts), 2)
    assert hits[0]["index"] == 1


def test_details_validation():
    assert client.post("/api/details", json={"firstName": "Sam", "mobile": "+1 415 555 0182"}).status_code == 201
    assert client.post("/api/details", json={"firstName": "Sam", "mobile": "abc"}).status_code == 422


def test_api_flow():
    parsed = client.post("/api/parse", files={"file": ("t.csv", CSV)}).json()
    emb = client.post("/api/embed", json={"texts": parsed["texts"]}).json()
    res = client.post("/api/search", json={"query": "pasta cook", "texts": parsed["texts"], "vectors": [emb["vectors"]]}).json()
    assert res["results"][0]["index"] == 2
