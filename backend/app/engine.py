"""Thin wrapper around the DATC-compliant `diplomacy` adjudicator.

Everything that touches the rules engine lives here so the rest of the app
only deals with plain JSON-able data.
"""
import json
from collections import OrderedDict
from typing import Dict, List, Optional

from diplomacy import Game as EngineGame
from diplomacy.utils.export import from_saved_game_format, to_saved_game_format

CLASSIC_POWERS = ["AUSTRIA", "ENGLAND", "FRANCE", "GERMANY", "ITALY", "RUSSIA", "TURKEY"]
RULES = ["NO_DEADLINE", "ALWAYS_WAIT", "IGNORE_ERRORS"]

SEASONS = {"S": "Spring", "F": "Fall", "W": "Winter"}
PHASE_TYPES = {"M": "Movement", "R": "Retreats", "A": "Adjustments"}


def phase_label(name: Optional[str]) -> str:
    if not name or len(name) < 6 or name[0] not in SEASONS:
        return name or ""
    try:
        year = str(int(name[1:5]))
    except ValueError:
        year = name[1:5]
    return f"{SEASONS[name[0]]} {year} {PHASE_TYPES.get(name[5], '')}".strip()


def new_game(map_name: str = "standard") -> EngineGame:
    return EngineGame(map_name=map_name, rules=list(RULES))


def load(state_json: str, map_name: Optional[str] = None) -> EngineGame:
    data = json.loads(state_json)
    if map_name:
        data["map"] = map_name  # generated maps live at a content-addressed path that may move
    return from_saved_game_format(data)


def powers(game: EngineGame) -> List[str]:
    return sorted(game.powers)


def dump(game: EngineGame) -> str:
    return json.dumps(to_saved_game_format(game))


def _state(game: EngineGame) -> dict:
    s = game.get_state()
    return {
        "units": {p: list(u) for p, u in s["units"].items()},
        "retreats": {p: {u: list(d) for u, d in r.items()} for p, r in s["retreats"].items()},
        "centers": {p: list(c) for p, c in s["centers"].items()},
        "influence": {p: list(i) for p, i in s["influence"].items()},
        "builds": s["builds"],
    }


def board(game: EngineGame) -> dict:
    out = _state(game)
    out["phase"] = game.get_current_phase()
    out["phase_type"] = game.phase_type
    out["phase_label"] = phase_label(out["phase"])
    out["eliminated"] = [p for p in powers(game) if game.powers[p].is_eliminated()]
    out["victory"] = int(game.victory[0]) if game.victory else None
    return out


_PO_CACHE: "OrderedDict[int, tuple]" = OrderedDict()


def _all_orders(game: EngineGame) -> Dict[str, List[str]]:
    """get_all_possible_orders() is the slow call; memoise it per game object + phase."""
    key = id(game)
    phase = game.get_current_phase()
    hit = _PO_CACHE.get(key)
    if hit and hit[0] is game and hit[1] == phase:
        _PO_CACHE.move_to_end(key)
        return hit[2]
    orders = game.get_all_possible_orders()
    _PO_CACHE[key] = (game, phase, orders)
    while len(_PO_CACHE) > 32:
        _PO_CACHE.popitem(last=False)
    return orders


def possible_orders(game: EngineGame, power: str) -> Dict[str, List[str]]:
    if game.is_game_done:
        return {}
    locs = game.get_orderable_locations(power)
    if not locs:
        return {}
    if game.phase_type == "A" and game.get_state()["builds"][power]["count"] == 0:
        return {}
    all_orders = _all_orders(game)
    return {loc: sorted(all_orders.get(loc, [])) for loc in locs if all_orders.get(loc)}


def needs_orders(game: EngineGame, power: str) -> bool:
    return bool(possible_orders(game, power))


def _province(loc: str) -> str:
    return loc.split("/")[0].upper()


def validate_orders(game: EngineGame, power: str, orders: List[str]) -> List[str]:
    """Return the cleaned order list or raise ValueError with a readable reason."""
    options = possible_orders(game, power)
    by_order = {}
    for loc, opts in options.items():
        for o in opts:
            by_order.setdefault(o, loc)

    cleaned: List[str] = []
    used_provinces = set()
    builds = disbands = waives = 0
    for raw in orders:
        order = " ".join(str(raw).upper().split())
        if order not in by_order:
            raise ValueError(f"Illegal order: {order}")
        if order == "WAIVE":
            waives += 1
            cleaned.append(order)
            continue
        prov = _province(by_order[order])
        if prov in used_provinces:
            raise ValueError(f"More than one order for {prov}")
        used_provinces.add(prov)
        if game.phase_type == "A":
            if order.endswith(" B"):
                builds += 1
            elif order.endswith(" D"):
                disbands += 1
        cleaned.append(order)

    if game.phase_type == "A":
        count = game.get_state()["builds"][power]["count"]
        if count > 0 and builds + waives > count:
            raise ValueError(f"You may build at most {count} unit(s)")
        if count < 0 and disbands > -count:
            raise ValueError(f"You only need to disband {-count} unit(s)")
    return cleaned


def process(game: EngineGame, orders_by_power: Dict[str, List[str]]) -> None:
    for power in powers(game):
        game.set_orders(power, orders_by_power.get(power, []))
    game.process()


def solo_winner(game: EngineGame) -> Optional[str]:
    need = int(game.victory[0]) if game.victory else len(game.map.scs) // 2 + 1
    for p in powers(game):
        if len(game.get_centers(p)) >= need:
            return p
    return None


def is_done(game: EngineGame) -> bool:
    return bool(game.is_game_done) or solo_winner(game) is not None


def alive_powers(game: EngineGame) -> List[str]:
    return [p for p in powers(game) if not game.powers[p].is_eliminated()]


# ---- history (read straight from the stored JSON, no engine needed) ----

def history_index(state_json: str) -> List[str]:
    phases = json.loads(state_json)["phases"]
    return [p["name"] for p in phases[:-1]]  # last entry is the live phase


def history_phase(state_json: str, name: str) -> Optional[dict]:
    phases = json.loads(state_json)["phases"]
    for i, ph in enumerate(phases[:-1]):
        if ph["name"] == name:
            st = ph["state"]
            return {
                "phase": ph["name"],
                "phase_label": phase_label(ph["name"]),
                "phase_type": ph["name"][-1],
                "units": st.get("units", {}),
                "retreats": st.get("retreats", {}),
                "centers": st.get("centers", {}),
                "influence": st.get("influence", {}),
                "builds": st.get("builds", {}),
                "orders": ph.get("orders", {}),
                "results": {u: [str(r) for r in res] for u, res in (ph.get("results") or {}).items()},
                "next_phase": phases[i + 1]["name"],
            }
    return None
