import json
from datetime import timedelta

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import service  # noqa: E402
from app.db import Game, SessionLocal, utcnow  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(scope="module")
def clients():
    with TestClient(app) as base:
        made = {}
        for name in ("alice", "bob", "carol"):
            c = TestClient(app)
            r = c.post("/api/auth/login", json={"username": name, "password": "password123"})
            if r.status_code != 200:
                r = c.post("/api/auth/register", json={"username": name, "password": "password123"})
            assert r.status_code == 200, r.text
            made[name] = c
        yield made


def test_auth(clients):
    assert clients["alice"].get("/api/me").json()["username"] == "alice"
    anon = TestClient(app)
    assert anon.get("/api/me").status_code == 401
    assert anon.post("/api/auth/login", json={"username": "alice", "password": "nope"}).status_code == 401
    assert anon.post("/api/auth/login", json={"username": "ALICE", "password": "password123"}).status_code == 200
    assert anon.post("/api/auth/register", json={"username": "Alice", "password": "password123"}).status_code == 409


def test_friends(clients):
    a, b = clients["alice"], clients["bob"]
    assert a.post("/api/friends/request", json={"username": "bob"}).json()["status"] == "pending"
    inc = b.get("/api/friends").json()["incoming"]
    assert len(inc) == 1 and inc[0]["user"]["username"] == "alice"
    assert b.post(f"/api/friends/{inc[0]['id']}/accept").status_code == 200
    assert a.get("/api/friends").json()["friends"][0]["user"]["username"] == "bob"
    assert a.post("/api/friends/request", json={"username": "nobody"}).status_code == 404


def test_full_game(clients):
    a, b, c = clients["alice"], clients["bob"], clients["carol"]
    g = a.post("/api/games", json={"name": "Old Guard", "deadline_minutes": 60, "assignment": "choice"}).json()
    gid, code = g["id"], g["invite_code"]

    bob_id = b.get("/api/me").json()["id"]
    carol_id = c.get("/api/me").json()["id"]
    assert a.post(f"/api/games/{gid}/invite", json={"user_id": carol_id}).status_code == 403  # not a friend
    assert a.post(f"/api/games/{gid}/invite", json={"user_id": bob_id}).status_code == 200
    invites = b.get("/api/games").json()["invites"]
    assert invites and invites[0]["game"]["id"] == gid
    assert c.get(f"/api/games/{gid}").status_code == 403
    assert b.post(f"/api/games/{gid}/join").status_code == 200
    assert c.post(f"/api/games/{gid}/join").status_code == 403
    assert c.post(f"/api/games/code/{code}/join").status_code == 200

    assert a.post(f"/api/games/{gid}/power", json={"power": "FRANCE"}).status_code == 200
    assert b.post(f"/api/games/{gid}/power", json={"power": "FRANCE"}).status_code == 409
    assert b.post(f"/api/games/{gid}/power", json={"power": "GERMANY"}).status_code == 200
    assert b.post(f"/api/games/{gid}/start").status_code == 403

    # lobby chat
    assert c.post(f"/api/games/{gid}/messages", json={"to": "GLOBAL", "body": "hi all"}).status_code == 200

    g = a.post(f"/api/games/{gid}/start").json()
    assert g["status"] == "active" and g["phase"] == "S1901M" and g["my_power"] == "FRANCE"
    assert "A PAR - BUR" in g["possible_orders"]["PAR"]
    powers = {p["username"]: p["power"] for p in g["players"]}
    assert powers["bob"] == "GERMANY" and powers["carol"] not in ("FRANCE", "GERMANY", None)

    # orders
    assert a.post(f"/api/games/{gid}/orders", json={"orders": ["A PAR - MOS"]}).status_code == 400
    assert a.post(f"/api/games/{gid}/orders", json={"orders": ["A PAR - BUR", "A PAR H"]}).status_code == 400
    assert a.post(f"/api/games/{gid}/orders", json={"orders": ["a par - bur", "A MAR S A PAR - BUR"]}).json()["orders"] == [
        "A PAR - BUR",
        "A MAR S A PAR - BUR",
    ]
    assert b.post(f"/api/games/{gid}/orders", json={"orders": ["A MUN - BUR"]}).status_code == 200
    # bob can't see alice's orders
    assert b.get(f"/api/games/{gid}").json()["my_orders"] == ["A MUN - BUR"]

    # press: private france -> germany
    assert a.post(f"/api/games/{gid}/messages", json={"to": "GERMANY", "body": "Stay out of Burgundy"}).status_code == 200
    assert a.post(f"/api/games/{gid}/messages", json={"to": "FRANCE", "body": "self"}).status_code == 400
    bodies = lambda cl: [m["body"] for m in cl.get(f"/api/games/{gid}/messages").json()]  # noqa: E731
    assert "Stay out of Burgundy" in bodies(b)
    assert "Stay out of Burgundy" not in bodies(c)
    assert "carol: hi all" in bodies(a)

    # readiness -> adjudication
    a.post(f"/api/games/{gid}/ready", json={"ready": True})
    b.post(f"/api/games/{gid}/ready", json={"ready": True})
    assert a.get(f"/api/games/{gid}").json()["phase"] == "S1901M"
    g = c.post(f"/api/games/{gid}/ready", json={"ready": True}).json()
    assert g["phase"] == "F1901M"
    units = g["board"]["units"]
    assert "A BUR" in units["FRANCE"] and "A MUN" in units["GERMANY"]
    assert g["history"] == ["S1901M"]
    h = a.get(f"/api/games/{gid}/history/S1901M").json()
    assert h["orders"]["FRANCE"] == ["A PAR - BUR", "A MAR S A PAR - BUR"]
    assert "bounce" in h["results"]["A MUN"]

    # deadline: nobody ready, clock runs out -> holds
    db = SessionLocal()
    game = db.get(Game, gid)
    game.deadline_at = utcnow() - timedelta(seconds=1)
    db.commit()
    db.close()
    assert gid in service.due_game_ids()
    assert service.process_if_ready(gid, force=True)
    g = a.get(f"/api/games/{gid}").json()
    assert g["phase"] == "S1902M"  # all units held: no centers change, winter is skipped
    assert g["deadline_at"] is not None

    # draw by unanimous vote of players
    for cl in (a, b, c):
        g = cl.post(f"/api/games/{gid}/draw", json={"vote": True}).json()
    assert g["status"] == "finished" and g["result"]["type"] == "draw"
    # all press revealed after the game ends
    assert "Stay out of Burgundy" in bodies(c)


def test_websocket_push(clients):
    a, b = clients["alice"], clients["bob"]
    g = a.post("/api/games", json={"name": "WS", "deadline_minutes": None}).json()
    b.post(f"/api/games/code/{g['invite_code']}/join")
    with b.websocket_connect("/ws") as ws:
        a.post(f"/api/games/{g['id']}/messages", json={"to": "GLOBAL", "body": "ping"})
        evt = json.loads(ws.receive_text())
        assert evt["type"] == "message" and evt["message"]["body"] == "alice: ping"


def test_civil_disorder_and_retreats():
    """One human, six CD powers: dislodgements of CD units and winter adjustments must not stall."""
    from app import engine

    eng = engine.new_game()
    engine.process(eng, {"FRANCE": ["A PAR - PIC", "A MAR - GAS"], "GERMANY": ["A MUN - BUR"]})
    engine.process(eng, {"FRANCE": ["A GAS - BUR", "A PIC S A GAS - BUR"]})
    assert eng.get_current_phase() == "F1901R"
    assert engine.needs_orders(eng, "GERMANY") and not engine.needs_orders(eng, "FRANCE")
    engine.process(eng, {})  # CD retreat -> disband
    assert eng.get_current_phase() == "W1901A"
    engine.process(eng, {})
    assert eng.get_current_phase() == "S1902M"
