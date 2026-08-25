"""Read-side helpers."""
import sqlite3


def exchange(conn: sqlite3.Connection, source_name: str, recording_external_id: str, kind: str = "gold") -> list[sqlite3.Row]:
    """All transmissions of one recording in time order, each with its transcript of the given kind."""
    return conn.execute(
        """SELECT x.id AS transmission_id, x.start_s, x.end_s, x.speaker_role, x.speaker_label, x.pilot_callsign,
                  t.normalized_text AS text
           FROM transmissions x
           JOIN recordings r ON r.id = x.recording_id
           JOIN sources s ON s.id = r.source_id
           LEFT JOIN transcripts t ON t.transmission_id = x.id AND t.kind = ?
           WHERE s.name = ? AND r.external_id = ?
           ORDER BY x.start_s, x.id""", (kind, source_name, recording_external_id)).fetchall()
