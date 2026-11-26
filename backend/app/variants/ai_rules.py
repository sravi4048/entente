"""Turn a map's plain-text special rules into proposed spec changes.

Runs once, at upload/review time — never during play. Every proposal is shown
to a reviewer, who applies the ones they agree with. The adjudicator only ever
sees the resulting adjacency data, so play stays deterministic.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List

from ..config import ANTHROPIC_API_KEY, ANTHROPIC_MODEL
from ..db import utcnow

OPS = ["add_adjacency", "remove_adjacency", "set_impassable", "set_supply_center", "set_build_anywhere", "set_victory"]


class AIError(Exception):
    pass


def enabled() -> bool:
    return bool(ANTHROPIC_API_KEY)


TOOL = {
    "name": "propose_map_changes",
    "description": "Report how each special rule maps onto the map's data, as a list of concrete changes.",
    "input_schema": {
        "type": "object",
        "properties": {
            "summary": {"type": "string", "description": "One or two sentences for the reviewer."},
            "changes": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "op": {"type": "string", "enum": OPS},
                        "a": {"type": "string", "description": "Location code, e.g. ABC or ABC/NC (adjacency ops)."},
                        "b": {"type": "string", "description": "Second location code (adjacency ops)."},
                        "type": {"type": "string", "enum": ["both", "army", "fleet"], "description": "add_adjacency: who can cross."},
                        "code": {"type": "string", "description": "Province code (set_impassable / set_supply_center)."},
                        "value": {"description": "true/false for set_* flags, an integer for set_victory."},
                        "rule": {"type": "string", "description": "The words from the rules this change implements."},
                        "explanation": {"type": "string"},
                    },
                    "required": ["op", "rule", "explanation"],
                },
            },
            "unenforceable": {
                "type": "array",
                "description": "Rules that can't be expressed as map data; players would follow them on the honor system.",
                "items": {
                    "type": "object",
                    "properties": {"rule": {"type": "string"}, "explanation": {"type": "string"}},
                    "required": ["rule", "explanation"],
                },
            },
        },
        "required": ["summary", "changes", "unenforceable"],
    },
}

SYSTEM = """You help review custom maps for the board game Diplomacy before they go live.
A map creator wrote special rules in plain English. Your job is to express each rule
as changes to the map's data, using only these operations:

- add_adjacency a b type   — let units move between two locations. type: both (armies and fleets),
                              army (land border only), fleet (water/coastal route only).
                              Canals, straits, bridges and tunnels are adjacencies.
- remove_adjacency a b     — two locations no longer border each other (e.g. a wall, a cliff).
- set_impassable code bool — nobody may ever enter the province.
- set_supply_center code bool
- set_build_anywhere bool  — builds allowed in any owned supply center, not only home centers.
- set_victory n            — supply centers needed to win.

Notation: a province code is 3 letters. Provinces with split coasts have locations like ABC/NC;
fleet adjacencies to such a province must name the coast. Armies never take a coast.
Only sea-to-sea, sea-to-coast and coast-to-coast links can carry fleets; landlocked provinces
can only have army links. Use the existing adjacency list to avoid duplicates, and to notice when
a rule only restricts an existing link (e.g. "fleets only" means remove, then add as fleet).

Anything the data can't express — extra unit strength, special unit types, neutral armies,
timed events, diplomacy or messaging rules, scoring tweaks — goes in `unenforceable`.
Never invent rules the creator didn't write. If the rules are empty or need no change,
return no changes. Always answer by calling propose_map_changes."""


def _context(spec: Dict[str, Any], report: Dict[str, Any]) -> str:
    lines = ["PROVINCES (code | name | type | flags | coasts)"]
    for p in spec.get("provinces", []):
        flags = ", ".join(f for f, on in (("supply center", p.get("sc")), ("impassable", p.get("impassable"))) if on)
        coasts = ", ".join(f"{c['name']} touches {'/'.join(c['seas'])}" for c in p.get("coasts", []) or [])
        lines.append(f"{p['code']} | {p['name']} | {p.get('type', 'land')} | {flags or '-'} | {coasts or '-'}")
    lines.append("")
    lines.append("CURRENT ADJACENCIES (a - b : who can cross)")
    for a in report.get("adjacency", []):
        lines.append(f"{a['a']} - {a['b']} : {a['type']}")
    lines.append("")
    lines.append("POWERS: " + ", ".join(f"{p['name']} (homes {' '.join(p.get('homes', []))})" for p in spec.get("powers", [])))
    stats = report.get("stats", {})
    lines.append(f"VICTORY: {stats.get('victory')} of {stats.get('supply_centers')} supply centers. "
                 f"BUILD ANYWHERE: {bool(spec.get('build_anywhere'))}")
    lines.append("")
    lines.append("SPECIAL RULES WRITTEN BY THE CREATOR:")
    lines.append(spec.get("rules") or "(none)")
    return "\n".join(lines)


def _clean(raw: Dict[str, Any], spec: Dict[str, Any]) -> Dict[str, Any]:
    provs = {str(p.get("code", "")).upper(): p for p in spec.get("provinces", [])}
    locs = set(provs)
    for code, p in provs.items():
        for c in p.get("coasts", []) or []:
            locs.add(f"{code}/{str(c.get('name', '')).upper()}")
    changes: List[dict] = []
    for i, ch in enumerate(raw.get("changes") or []):
        op = ch.get("op")
        if op not in OPS:
            continue
        item = {"id": i + 1, "op": op, "rule": str(ch.get("rule", ""))[:300], "explanation": str(ch.get("explanation", ""))[:500]}
        if op in ("add_adjacency", "remove_adjacency"):
            a, b = str(ch.get("a", "")).upper(), str(ch.get("b", "")).upper()
            if a not in locs or b not in locs or a.split("/")[0] == b.split("/")[0]:
                continue
            item.update(a=a, b=b)
            if op == "add_adjacency":
                item["type"] = ch.get("type") if ch.get("type") in ("both", "army", "fleet") else "both"
        elif op in ("set_impassable", "set_supply_center"):
            code = str(ch.get("code", "")).upper()
            if code not in provs:
                continue
            item.update(code=code, value=bool(ch.get("value", True)))
        elif op == "set_build_anywhere":
            item["value"] = bool(ch.get("value", True))
        elif op == "set_victory":
            try:
                item["value"] = int(ch.get("value"))
            except (TypeError, ValueError):
                continue
        changes.append(item)
    unenf = [{"rule": str(u.get("rule", ""))[:300], "explanation": str(u.get("explanation", ""))[:500]}
             for u in raw.get("unenforceable") or [] if isinstance(u, dict)]
    return {"summary": str(raw.get("summary", ""))[:800], "changes": changes, "unenforceable": unenf}


def interpret(spec: Dict[str, Any], report: Dict[str, Any], client=None) -> Dict[str, Any]:
    """Ask the model for proposals. `client` is injectable for tests."""
    if not (spec.get("rules") or "").strip():
        return {"summary": "No special rules were written, so nothing to change.", "changes": [], "unenforceable": [],
                "model": None, "created_at": utcnow().isoformat()}
    if client is None:
        if not enabled():
            raise AIError("Set ANTHROPIC_API_KEY to enable rule interpretation.")
        import anthropic

        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY, timeout=90)
    try:
        msg = client.messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=4000,
            system=SYSTEM,
            tools=[TOOL],
            tool_choice={"type": "tool", "name": TOOL["name"]},
            messages=[{"role": "user", "content": _context(spec, report)}],
        )
    except Exception as exc:  # network, auth, rate limit…
        raise AIError(f"The AI request failed: {exc}")
    block = next((b for b in msg.content if getattr(b, "type", None) == "tool_use"), None)
    if block is None:
        raise AIError("The AI didn't return structured changes.")
    data = block.input if isinstance(block.input, dict) else json.loads(block.input)
    out = _clean(data, spec)
    out["model"] = ANTHROPIC_MODEL
    out["created_at"] = utcnow().isoformat()
    return out
