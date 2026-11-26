import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from fastapi.testclient import TestClient

from app import api
from app.main import app
from app.variants import ai_rules

EX = Path(__file__).resolve().parent.parent / "app" / "examples" / "toy-islands"


def client_for(name: str) -> TestClient:
    c = TestClient(app)
    r = c.post("/api/auth/login", json={"username": name, "password": "password123"})
    if r.status_code != 200:
        r = c.post("/api/auth/register", json={"username": name, "password": "password123"})
        assert r.status_code == 200, r.text
    return c


@pytest.fixture(scope="module")
def users():
    with TestClient(app):
        # alice is created first in a fresh DB, which makes her the admin
        out = {n: client_for(n) for n in ("alice", "bob", "carol")}
        assert out["alice"].get("/api/me").json()["is_admin"] is True
        assert out["bob"].get("/api/me").json()["is_admin"] is False
        yield out


def files_png(spec_text=None):
    return {
        "spec_file": ("spec.yaml", spec_text or (EX / "spec.yaml").read_bytes(), "text/yaml"),
        "image": ("map.png", (EX / "map.png").read_bytes(), "image/png"),
        "mask": ("mask.png", (EX / "mask.png").read_bytes(), "image/png"),
    }


def test_builtin_variants_listed(users):
    v = users["carol"].get("/api/variants").json()
    assert [b["slug"] for b in v["builtin"]] == ["classic", "ancmed", "modern"]
    anc = next(b for b in v["builtin"] if b["slug"] == "ancmed")
    assert anc["players"] == 5 and anc["victory"] == 18
    geo = users["carol"].get("/api/variants/modern/map").json()
    assert len(geo["provinces"]) > 100 and len(geo["powers"]) == 10


def test_play_ancmed(users):
    a, b = users["alice"], users["bob"]
    g = a.post("/api/games", json={"name": "Rome", "variant": "ancmed", "deadline_minutes": None}).json()
    assert g["variant"]["slug"] == "ancmed" and sorted(g["powers"]) == ["CARTHAGE", "EGYPT", "GREECE", "PERSIA", "ROME"]
    b.post(f"/api/games/code/{g['invite_code']}/join")
    g = a.post(f"/api/games/{g['id']}/start").json()
    assert g["status"] == "active" and g["phase"] == "S0001M" and g["phase_label"] == "Spring 1 Movement"
    assert g["my_power"] in g["powers"] and g["possible_orders"]
    assert a.get(f"/api/games/{g['id']}/map").json()["powers"][0]["name"] == "CARTHAGE"
    for c in (a, b):
        c.post(f"/api/games/{g['id']}/ready", json={"ready": True})
    assert a.get(f"/api/games/{g['id']}").json()["phase"] == "F0001M"


def test_upload_validation_errors(users):
    b = users["bob"]
    files = files_png()
    del files["mask"]
    r = b.post("/api/variants", files=files)
    assert r.status_code == 422 and "mask" in r.json()["detail"]["errors"][0]
    bad = yaml.safe_load((EX / "spec.yaml").read_text())
    bad["powers"][0]["homes"] = ["WES"]
    bad["powers"][1]["name"] = "TOO"
    r = b.post("/api/variants", files=files_png(yaml.safe_dump(bad).encode()))
    errs = r.json()["detail"]["errors"]
    assert r.status_code == 422 and any("3 letters" in e for e in errs)


def test_upload_review_and_play(users, monkeypatch):
    a, b, c = users["alice"], users["bob"], users["carol"]

    # dry run returns a preview without saving
    r = b.post("/api/variants", files=files_png(), data={"dry_run": "true"})
    assert r.status_code == 200, r.text
    rep = r.json()["report"]
    assert rep["errors"] == [] and rep["stats"]["supply_centers"] == 6 and rep["stats"]["victory"] == 4
    adj = {(x["a"], x["b"]): x["type"] for x in rep["adjacency"]}
    assert adj[("CCC", "EEE")] == "army" and adj[("EEE", "FFF")] == "both" and adj[("AAA", "DDD/WC")] == "fleet"
    assert b.get("/api/variants").json()["mine"] == []

    v = b.post("/api/variants", files=files_png()).json()
    slug = v["slug"]
    assert v["status"] == "pending" and v["slug"] == "toy-islands" and v["has_image"]
    assert c.get(f"/api/variants/{slug}").status_code == 404  # not visible to others yet
    assert [q["slug"] for q in a.get("/api/variants").json()["queue"]] == [slug]
    assert c.post("/api/games", json={"name": "x", "variant": slug}).status_code == 400
    # the author can playtest before approval
    assert b.post("/api/games", json={"name": "Playtest", "variant": slug}).status_code == 200

    # AI interpretation, with a fake client standing in for the API
    proposal = {
        "summary": "One canal.",
        "changes": [
            {"op": "add_adjacency", "a": "AAA", "b": "CCC", "type": "fleet", "rule": "canal", "explanation": "x"},
            {"op": "add_adjacency", "a": "AAA", "b": "ZZZ", "type": "fleet", "rule": "bogus", "explanation": "unknown code"},
        ],
        "unenforceable": [{"rule": "Scarlet moves first", "explanation": "orders are simultaneous"}],
    }
    fake = SimpleNamespace(messages=SimpleNamespace(create=lambda **kw: SimpleNamespace(
        content=[SimpleNamespace(type="tool_use", input=proposal)])))
    spec = yaml.safe_load((EX / "spec.yaml").read_text())
    out = ai_rules.interpret(spec, rep, client=fake)
    assert [ch["b"] for ch in out["changes"]] == ["CCC"] and out["unenforceable"]

    # apply the accepted change → rebuilt and re-validated
    v = b.post(f"/api/variants/{slug}/apply", json={"changes": [out["changes"][0]]}).json()
    adj = {(x["a"], x["b"]): x["type"] for x in v["report"]["adjacency"]}
    assert adj[("AAA", "CCC")] == "fleet" and v["version"] == 2

    # review
    assert b.post(f"/api/variants/{slug}/review", json={"action": "approve"}).status_code == 403
    v = a.post(f"/api/variants/{slug}/review", json={"action": "approve", "note": "Nice"}).json()
    assert v["status"] == "approved"
    assert slug in [x["slug"] for x in c.get("/api/variants").json()["approved"]]

    # play it
    g = c.post("/api/games", json={"name": "Islands", "variant": slug, "assignment": "choice", "deadline_minutes": None}).json()
    a.post(f"/api/games/code/{g['invite_code']}/join")
    c.post(f"/api/games/{g['id']}/power", json={"power": "SCARLET"})
    g = c.post(f"/api/games/{g['id']}/start").json()
    assert g["my_power"] == "SCARLET"
    assert "F AAA - CCC" in g["possible_orders"]["AAA"]  # the canal
    geo = c.get(f"/api/games/{g['id']}/map").json()
    assert geo["style"] == "image" and geo["image"] == f"/api/variants/{slug}/image"
    img = c.get(geo["image"])
    assert img.headers["content-type"] == "image/png" and "sandbox" in img.headers["content-security-policy"]
    c.post(f"/api/games/{g['id']}/orders", json={"orders": ["F AAA - CCC"]})
    for cl in (a, c):
        cl.post(f"/api/games/{g['id']}/ready", json={"ready": True})
    g = c.get(f"/api/games/{g['id']}").json()
    assert g["phase"] == "F1901M" and "F CCC" not in g["board"]["units"]["SCARLET"]  # bounced vs VERDANT's fleet
    # games keep their own snapshot, so the map can't be deleted out from under them
    assert a.delete(f"/api/variants/{slug}").status_code == 400


def test_svg_upload(users):
    b = users["bob"]
    spec = yaml.safe_load((EX / "spec.yaml").read_text())
    spec["name"] = "Toy Islands SVG"
    for p in spec["provinces"]:
        p.pop("color", None)  # SVG uploads don't need mask colors
    r = b.post("/api/variants", files={
        "spec_file": ("spec.yaml", yaml.safe_dump(spec).encode(), "text/yaml"),
        "image": ("map.svg", (EX / "map.svg").read_bytes(), "image/svg+xml"),
    })
    assert r.status_code == 200, r.text
    v = r.json()
    assert v["source_format"] == "svg" and len(v["report"]["adjacency"]) == 17 and v["report"]["errors"] == []
    img = b.get(f"/api/variants/{v['slug']}/image")
    assert img.headers["content-type"].startswith("image/svg+xml")
    assert b.delete(f"/api/variants/{v['slug']}").status_code == 200


def test_signup_code(monkeypatch):
    monkeypatch.setattr(api, "SIGNUP_CODE", "Backstab")
    c = TestClient(app)
    assert c.post("/api/auth/register", json={"username": "dave", "password": "password123"}).status_code == 403
    assert c.post("/api/auth/register", json={"username": "dave", "password": "password123", "invite_code": "backstab"}).status_code == 200
    assert c.get("/api/config").json()["signup_code_required"] is True


def test_multiple_signup_codes(monkeypatch):
    monkeypatch.setattr(api, "SIGNUP_CODE", "pope-francis's-devil, jd-vance")
    c = TestClient(app)
    reg = lambda u, code: c.post("/api/auth/register", json={"username": u, "password": "password123", "invite_code": code}).status_code
    assert reg("erin", "wrong") == 403
    assert reg("erin", "JD-Vance") == 200
    assert reg("frank", "pope-francis's-devil") == 200
