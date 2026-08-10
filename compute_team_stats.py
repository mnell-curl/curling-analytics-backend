"""
Compute team-level summary stats (wins, losses, stolen ends, blanked ends,
hammer conversion %, steal %) from the games/ends tables and write them
into team_season_stats.

Usage:
    py compute_team_stats.py <season_label>

Example:
    py compute_team_stats.py 2024-25

Definitions used here (adjust if you want different conventions):
- Stolen end: a team scores 1+ points in an end where they did NOT have hammer.
- Blanked end: both teams score 0 points in an end (no one converts).
- Hammer conversion %: of the ends where a team HAD hammer, the % where they
  scored 1+ points (didn't get blanked or stolen off of).
- Steal %: of the ends where a team did NOT have hammer, the % where they
  scored 1+ points (i.e. stole).
"""

import sqlite3
import sys

DB_PATH = "curling.db"


def create_table(conn):
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS team_season_stats (
            team_id INTEGER REFERENCES teams(team_id),
            season TEXT,
            wins INTEGER,
            losses INTEGER,
            stolen_ends INTEGER,
            blanked_ends INTEGER,
            hammer_conversion_pct REAL,
            steal_pct REAL,
            PRIMARY KEY (team_id, season)
        );
        """
    )
    conn.commit()


def compute_stats(season: str):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    create_table(conn)
    cur = conn.cursor()

    # All teams that appear in a game this season
    cur.execute(
        """
        SELECT DISTINCT team_id FROM teams WHERE season = ?
        """,
        (season,),
    )
    team_ids = [row["team_id"] for row in cur.fetchall()]

    for team_id in team_ids:
        wins = 0
        losses = 0

        # --- Wins / losses from games table ---
        cur.execute(
            """
            SELECT game_id, team1_id, team2_id, team1_score, team2_score
            FROM games
            WHERE team1_id = ? OR team2_id = ?
            """,
            (team_id, team_id),
        )
        games = cur.fetchall()

        game_ids = []
        for g in games:
            game_ids.append(g["game_id"])
            is_team1 = g["team1_id"] == team_id
            own_score = g["team1_score"] if is_team1 else g["team2_score"]
            opp_score = g["team2_score"] if is_team1 else g["team1_score"]
            if own_score > opp_score:
                wins += 1
            elif own_score < opp_score:
                losses += 1
            # ties basically don't happen in curling (ends decide it), but
            # if data is weird, this just won't count it either way

        if not game_ids:
            continue

        # --- End-level stats ---
        stolen_ends = 0
        blanked_ends = 0
        hammer_ends_played = 0
        hammer_ends_scored = 0
        no_hammer_ends_played = 0
        no_hammer_ends_scored = 0

        placeholders = ",".join("?" for _ in game_ids)
        cur.execute(
            f"""
            SELECT e.game_id, e.team1_points, e.team2_points, e.hammer_team_id,
                   g.team1_id, g.team2_id
            FROM ends e
            JOIN games g ON g.game_id = e.game_id
            WHERE e.game_id IN ({placeholders})
            """,
            game_ids,
        )
        end_rows = cur.fetchall()

        for e in end_rows:
            is_team1 = e["team1_id"] == team_id
            own_points = e["team1_points"] if is_team1 else e["team2_points"]
            had_hammer = e["hammer_team_id"] == team_id

            if e["team1_points"] == 0 and e["team2_points"] == 0:
                blanked_ends += 1

            if had_hammer:
                hammer_ends_played += 1
                if own_points > 0:
                    hammer_ends_scored += 1
            else:
                no_hammer_ends_played += 1
                if own_points > 0:
                    no_hammer_ends_scored += 1
                    stolen_ends += 1

        hammer_conversion_pct = (
            round(100 * hammer_ends_scored / hammer_ends_played, 1)
            if hammer_ends_played
            else None
        )
        steal_pct = (
            round(100 * no_hammer_ends_scored / no_hammer_ends_played, 1)
            if no_hammer_ends_played
            else None
        )

        cur.execute(
            """
            INSERT INTO team_season_stats (
                team_id, season, wins, losses, stolen_ends, blanked_ends,
                hammer_conversion_pct, steal_pct
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(team_id, season) DO UPDATE SET
                wins = excluded.wins,
                losses = excluded.losses,
                stolen_ends = excluded.stolen_ends,
                blanked_ends = excluded.blanked_ends,
                hammer_conversion_pct = excluded.hammer_conversion_pct,
                steal_pct = excluded.steal_pct
            """,
            (
                team_id,
                season,
                wins,
                losses,
                stolen_ends,
                blanked_ends,
                hammer_conversion_pct,
                steal_pct,
            ),
        )

    conn.commit()
    conn.close()
    print(f"Computed team_season_stats for {len(team_ids)} teams in season {season}.")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: py compute_team_stats.py <season_label>")
        sys.exit(1)

    compute_stats(sys.argv[1])
