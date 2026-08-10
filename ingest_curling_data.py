"""
Ingest CurlingZone boxscore data for an event into the SQLite schema
from the curling analytics design doc.

Usage:
    py ingest_curling_data.py <cz_event_id> <season_label>

Example:
    py ingest_curling_data.py 9478 2024-25
"""

import re
import sqlite3
import sys
from collections import defaultdict

import czapi.api as api

DB_PATH = "curling.db"


def create_tables(conn):
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS teams (
            team_id INTEGER PRIMARY KEY,
            skip_name TEXT NOT NULL,
            association TEXT,
            season TEXT
        );

        CREATE TABLE IF NOT EXISTS games (
            game_id TEXT PRIMARY KEY,
            event_name TEXT,
            draw_number INTEGER,
            date TEXT,
            team1_id INTEGER REFERENCES teams(team_id),
            team2_id INTEGER REFERENCES teams(team_id),
            team1_score INTEGER,
            team2_score INTEGER,
            team1_hammer_start BOOLEAN
        );

        CREATE TABLE IF NOT EXISTS ends (
            game_id TEXT REFERENCES games(game_id),
            end_number INTEGER,
            team1_points INTEGER,
            team2_points INTEGER,
            hammer_team_id INTEGER,
            PRIMARY KEY (game_id, end_number)
        );
        """
    )
    conn.commit()


def extract_team_id(href: str) -> int:
    """Pull the numeric teamid out of a Boxscore.href string."""
    match = re.search(r"teamid=(\d+)", href)
    if not match:
        raise ValueError(f"Could not find teamid in href: {href}")
    return int(match.group(1))


def played_ends(score_list):
    """Trim off trailing 'X' entries (ends not played because game ended early)."""
    return [int(s) for s in score_list if s != "X"]


def get_event_name(cz_event_id: int) -> str:
    """
    Event doesn't expose event_name directly, but LinescorePage does.
    Assumes event_name is constant across all draws in the event, so we
    only need to fetch draw 1's metadata (avoids one request per draw).
    """
    page = api.LinescorePage(cz_event_id=cz_event_id, cz_draw_id=1)
    return page.event_name


def ingest_event(cz_event_id: int, season: str):
    event = api.Event(cz_event_id=cz_event_id)
    if not event.is_valid:
        raise ValueError(f"Event ID {cz_event_id} is not valid")

    event_name = get_event_name(cz_event_id)
    boxscores = event.get_flat_boxscores()

    # Pair up the two Boxscore rows that belong to the same game via guid
    games_by_guid = defaultdict(list)
    for bs in boxscores:
        games_by_guid[bs.guid].append(bs)

    conn = sqlite3.connect(DB_PATH)
    create_tables(conn)
    cur = conn.cursor()

    games_inserted = 0
    ends_inserted = 0

    for guid, pair in games_by_guid.items():
        if len(pair) != 2:
            # Skip anything that isn't a clean two-team game (byes, walkovers, etc.)
            continue

        team1, team2 = pair
        team1_id = extract_team_id(team1.href)
        team2_id = extract_team_id(team2.href)

        # Upsert teams
        for tid, bs in ((team1_id, team1), (team2_id, team2)):
            cur.execute(
                """
                INSERT INTO teams (team_id, skip_name, association, season)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(team_id) DO UPDATE SET
                    skip_name = excluded.skip_name,
                    season = excluded.season
                """,
                (tid, bs.team_name, None, season),
            )

        game_id = str(guid)
        cur.execute(
            """
            INSERT INTO games (
                game_id, event_name, draw_number, date,
                team1_id, team2_id, team1_score, team2_score, team1_hammer_start
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(game_id) DO NOTHING
            """,
            (
                game_id,
                event_name,
                team1.draw_num,
                None,  # per-draw date not fetched; add back a LinescorePage lookup per draw if you need this
                team1_id,
                team2_id,
                int(team1.final_score),
                int(team2.final_score),
                bool(team1.hammer_start),
            ),
        )
        games_inserted += 1

        t1_ends = played_ends(team1.score)
        t2_ends = played_ends(team2.score)
        num_ends = min(len(t1_ends), len(t2_ends))

        for i in range(num_ends):
            hammer_team_id = team1_id if team1.hammer_progression[i] else team2_id
            cur.execute(
                """
                INSERT INTO ends (game_id, end_number, team1_points, team2_points, hammer_team_id)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(game_id, end_number) DO NOTHING
                """,
                (game_id, i + 1, t1_ends[i], t2_ends[i], hammer_team_id),
            )
            ends_inserted += 1

    conn.commit()
    conn.close()

    print(f"Ingested {games_inserted} games and {ends_inserted} ends from event {cz_event_id}.")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: py ingest_curling_data.py <cz_event_id> <season_label>")
        sys.exit(1)

    event_id = int(sys.argv[1])
    season_label = sys.argv[2]
    ingest_event(event_id, season_label)