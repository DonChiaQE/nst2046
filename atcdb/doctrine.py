"""The regulatory basis for the engine's rules, stored in `phraseology_rules` (spec addendum A.3.8).

Each rule the engine applies either cites the ICAO Doc 4444 (PANS-ATM) paragraph it encodes or is marked an
engineering heuristic with no regulatory basis. The engine detects incompatible clearances, a proxy for the physical
separation Doc 4444 actually governs, so citations say what a rule is derived from, not that the engine enforces it.
Wording is quoted from Doc 4444, 16th edition, Chapter 7.
"""
import sqlite3

DOC_4444 = "ICAO Doc 4444 (PANS-ATM)"
HEURISTIC = "engineering heuristic"

RULES: list[dict] = [
    {"id": "icao-4444-7.10.2", "document": DOC_4444, "section": "7.10.2", "category": "reservation", "pattern": "LAND",
     "description": "An aircraft may be cleared to land when there is reasonable assurance that the separation in 7.10.1 "
                    "will exist when the aircraft crosses the runway threshold. Basis for: a landing clearance reserves "
                    "the runway."},
    {"id": "icao-4444-7.9.3.1", "document": DOC_4444, "section": "7.9.3.1", "category": "reservation", "pattern": "TAKEOFF",
     "description": "Take-off clearance may be issued when there is reasonable assurance that the separation in 7.9.2 "
                    "will exist when the aircraft commences take-off. Basis for: a take-off clearance reserves the runway."},
    {"id": "icao-4444-7.10.2-proviso", "document": DOC_4444, "section": "7.10.2", "category": "compatibility",
     "pattern": "LAND/LAND",
     "description": "A clearance to land shall not be issued until a preceding landing aircraft has crossed the runway "
                    "threshold, so successive landing clearances are lawful. Basis for: LAND after LAND is not a conflict."},
    {"id": "icao-4444-7.9.2", "document": DOC_4444, "section": "7.9.2", "category": "compatibility", "pattern": "TAKEOFF/LAND",
     "description": "A departing aircraft will not normally be permitted to commence take-off until the preceding departing "
                    "aircraft has crossed the end of the runway-in-use or has started a turn or until all preceding "
                    "landing aircraft are clear of the runway-in-use. Basis for: a take-off clearance against a held "
                    "landing clearance is an alert."},
    {"id": "icao-4444-7.10.1", "document": DOC_4444, "section": "7.10.1", "category": "compatibility", "pattern": "LAND/TAKEOFF",
     "description": "A landing aircraft will not normally be permitted to cross the runway threshold on its final approach "
                    "until the preceding departing aircraft has crossed the end of the runway-in-use, or has started a "
                    "turn, or until all preceding landing aircraft are clear of the runway-in-use. Basis for: a landing "
                    "clearance against a held take-off clearance is an alert."},
    {"id": "heuristic-handoff-release", "document": HEURISTIC, "section": None, "category": "release", "pattern": "HANDOFF",
     "description": "A handoff to ground releases LAND and CROSS; a handoff to departure releases TAKEOFF. No ICAO basis: "
                    "7.9.2 and 7.10.1 turn on the preceding aircraft being clear of the runway-in-use, which the "
                    "controller observes and never transmits. The handoff is the transmitted proxy."},
    {"id": "heuristic-staleness", "document": HEURISTIC, "section": None, "category": "release", "pattern": "STALE_S",
     "description": "A reservation older than its kind's timeout is dropped silently. No ICAO basis: a fallback for release "
                    "calls that were never transmitted."},
]


_COLUMNS = ("id", "document", "section", "category", "pattern", "description")


def seed(conn: sqlite3.Connection) -> None:
    """Write RULES into `phraseology_rules`, replacing rows by id. Idempotent, and a no-op (no write, no commit)
    when the table already holds exactly RULES: `init_db` calls this on every open, including once per API
    request, so a table that already matches must cost nothing."""
    current = {row[0]: tuple(row) for row in conn.execute(f"SELECT {', '.join(_COLUMNS)} FROM phraseology_rules")}
    wanted = {r["id"]: tuple(r[c] for c in _COLUMNS) for r in RULES}
    if current == wanted:
        return
    conn.executemany("INSERT OR REPLACE INTO phraseology_rules (id, document, section, category, pattern, description) "
                     "VALUES (:id, :document, :section, :category, :pattern, :description)", RULES)
    conn.commit()
