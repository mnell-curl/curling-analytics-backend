"""
CurlingZone roster + player-profile scraper — separate from czapi, since
this targets home.curlingzone.com (team.php / player.php), a different,
newer part of the site than the event.php pages czapi scrapes.

Usage:
    py roster_scraper.py team <team_id>
    py roster_scraper.py player <player_id>

Examples:
    py roster_scraper.py team 1005604
    py roster_scraper.py player 26570

`team` mode scrapes a team's current roster, then automatically scrapes
each player's profile too (age, born, resides, throws, profession).
`player` mode scrapes one player's profile PLUS their full team history
(every team/season/discipline they've played on, going back years).

IMPORTANT CAVEAT: `team.php` shows CurlingZone's CURRENT roster for a
team_id, as of today — not necessarily the roster at some specific past
event you've already ingested via ingest_curling_data.py. Curling lineups
change between seasons. If you need historical, per-event rosters, that's
event.php?view=Team&eventid=X&teamid=Y (the `href` field already sitting
on each Boxscore from czapi) — a DIFFERENT, unconfirmed page structure.
Grab its HTML the same way we validated this one before scraping it.
"""

import re
import sqlite3
import sys

import requests
from bs4 import BeautifulSoup

DB_PATH = "curling.db"
TEAM_URL = "https://home.curlingzone.com/team.php"
PLAYER_URL = "https://home.curlingzone.com/player.php"


def create_tables(conn):
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS players (
            player_id INTEGER PRIMARY KEY,
            name TEXT,
            age TEXT,
            born TEXT,
            resides TEXT,
            throws TEXT,
            profession TEXT,
            high_school TEXT,
            scraped_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS rosters (
            team_id INTEGER,
            player_id INTEGER,
            label TEXT,
            source TEXT,
            scraped_at TEXT DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (team_id, player_id)
        );

        CREATE TABLE IF NOT EXISTS player_team_history (
            player_id INTEGER,
            team_id INTEGER,
            discipline TEXT,
            season TEXT,
            location TEXT,
            PRIMARY KEY (player_id, team_id, season, discipline)
        );
        """
    )
    conn.commit()

    # Migrations for databases created before these columns existed —
    # add them if missing rather than forcing a fresh curling.db.
    cur = conn.cursor()

    cur.execute("PRAGMA table_info(games)")
    game_columns = {row[1] for row in cur.fetchall()}
    for col, decl in [
        ("cz_game_id", "INTEGER"),   # CurlingZone's own game.php ID — different from czapi's guid
        ("draw_date", "TEXT"),
        ("draw_time", "TEXT"),
    ]:
        if col not in game_columns:
            cur.execute(f"ALTER TABLE games ADD COLUMN {col} {decl}")

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS events (
            event_id INTEGER PRIMARY KEY,
            event_name TEXT,
            season TEXT
        )
        """
    )
    cur.execute("PRAGMA table_info(events)")
    event_columns = {row[1] for row in cur.fetchall()}
    for col, decl in [
        ("sfm_points", "REAL"),
        ("venue", "TEXT"),
        ("location", "TEXT"),
        ("num_teams", "INTEGER"),
        ("format", "TEXT"),
        ("purse", "TEXT"),
        ("dates", "TEXT"),
    ]:
        if col not in event_columns:
            cur.execute(f"ALTER TABLE events ADD COLUMN {col} {decl}")

    conn.commit()


def save_roster(team_id: int, players: list, source: str):
    """source: 'team.php' (current roster) or 'event.php' (event-specific roster)."""
    conn = sqlite3.connect(DB_PATH)
    create_tables(conn)
    cur = conn.cursor()
    for p in players:
        label = p.get("position") or p.get("label")
        cur.execute(
            """
            INSERT INTO rosters (team_id, player_id, label, source)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(team_id, player_id) DO UPDATE SET
                label = excluded.label,
                source = excluded.source,
                scraped_at = CURRENT_TIMESTAMP
            """,
            (team_id, p["player_id"], label, source),
        )
    conn.commit()
    conn.close()


def save_player_profile(profile: dict):
    conn = sqlite3.connect(DB_PATH)
    create_tables(conn)
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO players (player_id, name, age, born, resides, throws, profession, high_school)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(player_id) DO UPDATE SET
            name = excluded.name,
            age = excluded.age,
            born = excluded.born,
            resides = excluded.resides,
            throws = excluded.throws,
            profession = excluded.profession,
            high_school = excluded.high_school,
            scraped_at = CURRENT_TIMESTAMP
        """,
        (
            profile["player_id"], profile["name"], profile.get("age"), profile.get("born"),
            profile.get("resides"), profile.get("throws"), profile.get("profession"),
            profile.get("high_school"),
        ),
    )
    conn.commit()
    conn.close()


def save_player_team_history(player_id: int, history: list):
    conn = sqlite3.connect(DB_PATH)
    create_tables(conn)
    cur = conn.cursor()
    for h in history:
        cur.execute(
            """
            INSERT INTO player_team_history (player_id, team_id, discipline, season, location)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(player_id, team_id, season, discipline) DO UPDATE SET
                location = excluded.location
            """,
            (player_id, h["team_id"], h["discipline"], h["season"], h["location"]),
        )
    conn.commit()
    conn.close()


# ---------- Roster (team.php) ----------

def scrape_roster(team_id: int) -> dict:
    resp = requests.get(TEAM_URL, params={"teamid": team_id}, timeout=10)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    card = soup.find("div", class_="card")
    if card is None:
        raise ValueError(f"No team card found for team_id {team_id} — check the ID is valid")

    team_name = card.find("span", class_="fw-semibold").get_text(strip=True)
    season = card.find("span", class_="badge").get_text(strip=True)

    location = card.find("div", class_="text-end")
    club = location.find("div", class_="fw-semibold").get_text(strip=True) if location else None
    country_div = location.find("div", class_="text-muted small") if location else None
    country = country_div.get_text(strip=True) if country_div else None

    roster_div = card.find("div", class_="d-flex flex-wrap gap-3")
    player_blocks = roster_div.find_all("div", class_="text-center", recursive=False)

    players = []
    for block in player_blocks:
        position_div = block.find("div", class_="small mt-1")
        position = position_div.get_text(strip=True)

        name_link = block.find("div", class_="small fw-semibold").find("a")
        name = name_link.get_text(strip=True)
        player_id = int(name_link["href"].split("playerid=")[1])

        players.append({"position": position, "player_id": player_id, "player_name": name})

    return {
        "team_id": team_id,
        "team_name": team_name,
        "season": season,
        "club": club,
        "country": country,
        "players": players,
    }


# ---------- Player profile (player.php) ----------

def scrape_player_profile(player_id: int) -> dict:
    resp = requests.get(PLAYER_URL, params={"playerid": player_id}, timeout=10)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    card = soup.find("div", class_="card")
    info_div = card.find("div", class_="flex-grow-1")
    name = info_div.find("h2").get_text(strip=True)

    fields = {}
    for div in info_div.find_all("div", recursive=False):
        strong = div.find("strong")
        if strong is None:
            continue
        label = strong.get_text(strip=True).rstrip(":")
        value = div.get_text(strip=True).replace(strong.get_text(strip=True), "", 1).strip()
        fields[label] = value

    return {
        "player_id": player_id,
        "name": name,
        "age": fields.get("Age"),
        "born": fields.get("Born"),
        "resides": fields.get("Resides"),
        "throws": fields.get("Throws"),
        "profession": fields.get("Profession"),
        "high_school": fields.get("High School"),
    }


# ---------- Player team history (player.php?view=Teams) ----------

def scrape_player_team_history(player_id: int) -> list:
    resp = requests.get(PLAYER_URL, params={"playerid": player_id, "view": "Teams"}, timeout=10)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    # Find the "Team History" card specifically — the page also has the
    # profile card and possibly other cards, so don't just grab the first one.
    history_card = None
    for card in soup.find_all("div", class_="card"):
        header = card.find("div", class_="card-header")
        if header and "Team History" in header.get_text():
            history_card = card
            break

    if history_card is None:
        return []

    card_body = history_card.find("div", class_="card-body")
    entries = card_body.find_all("div", class_="mb-3", recursive=False)

    history = []
    for entry in entries:
        header = entry.find("div", class_="d-flex flex-wrap justify-content-between align-items-center gap-2 mb-2")
        if header is None:
            continue

        team_link = header.find("a")
        team_id = int(team_link["href"].split("teamid=")[1])

        badge = header.find("span", class_="badge")
        discipline = badge.get_text(strip=True) if badge else None

        season_span = header.find("span", class_="text-muted small")
        season_line = season_span.get_text(strip=True) if season_span else ""
        # season_line looks like "2026/27 — Stirling, SCO"
        if "—" in season_line:
            season, location = [s.strip() for s in season_line.split("—", 1)]
        else:
            season, location = season_line, None

        history.append({
            "team_id": team_id,
            "discipline": discipline,
            "season": season,
            "location": location,
        })

    return history


# ---------- Event-specific team page (event.php?view=Team) ----------
# NOTE: confirmed structure so far is from a Mixed Doubles event (2 players,
# labeled Female/Male via <font color='blue'>). A traditional 4-player
# team's version of this page (Skip/Third/Second/Lead) is NOT YET
# confirmed — the label-extraction logic below should generalize to it
# (it just reads whatever text is in the <font> tag), but verify against
# real markup before trusting it blindly on a 4-player event.

EVENT_TEAM_URL = "https://www.curlingzone.com/event.php"


def scrape_event_team(cz_event_id: int, team_id: int) -> dict:
    resp = requests.get(
        EVENT_TEAM_URL,
        params={"view": "Team", "eventid": cz_event_id, "teamid": team_id},
        timeout=10,
    )
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    # --- Roster ---
    players = []
    for cell in soup.find_all("td", valign="top", align="center"):
        links = cell.find_all("a")
        if not links:
            continue
        font = cell.find("font")
        label = font.get_text(strip=True) if font else None
        name_link = links[-1]
        if "playerid=" not in name_link.get("href", ""):
            continue
        player_id = int(name_link["href"].split("playerid=")[1].split("#")[0])
        name = " ".join(name_link.stripped_strings)
        players.append({"label": label, "player_id": player_id, "name": name})

    # --- Per-event statistics tables (RECORD, SCORING, WITH/WITHOUT HAMMER) ---
    stats = {}
    for table in soup.find_all("table", class_="rwd-table"):
        header_row = table.find("tr")
        table_name = header_row.find("th").get_text(strip=True)
        headers = [th.get_text(strip=True) for th in header_row.find_all("th")][1:]

        data_rows = table.find_all("tr")[1:]
        if not data_rows:
            continue
        cells = data_rows[0].find_all("td")[1:]
        values = [c.get_text(strip=True) for c in cells]

        stats[table_name] = dict(zip(headers, values))

    # --- SFM (World Curling ranking points multiplier for this event) ---
    # Sits in the sidebar nav on every event.php page, regardless of view.
    sfm_link = soup.find("a", href=lambda h: h and "view=SFM" in h)
    sfm = sfm_link.get_text(strip=True).replace("SFM:", "").strip() if sfm_link else None

    # --- Schedule table (bridges our games.game_id (czapi's guid) to
    # CurlingZone's own game.php showgameid, via draw_number) ---
    schedule = []
    schedule_table = soup.find("table", class_="yspwhitebg")
    if schedule_table:
        for row in schedule_table.find_all("tr")[1:]:  # skip header row
            cells = row.find_all("td")
            if len(cells) < 3:
                continue
            draw_text = cells[0].get_text(strip=True)
            game_link = cells[2].find("a")
            if not draw_text.isdigit() or game_link is None:
                continue
            href = game_link.get("href", "")
            id_match = re.search(r"showgameid=(\d+)", href)
            if not id_match:
                continue
            schedule.append({"draw_number": int(draw_text), "cz_game_id": int(id_match.group(1))})

    return {
        "event_id": cz_event_id,
        "team_id": team_id,
        "players": players,
        "stats": stats,
        "sfm": sfm,
        "schedule": schedule,
    }


def save_game_ids(event_id: int, team_id: int, schedule: list):
    """
    Bridges CurlingZone's own game.php IDs into our games table (keyed by
    czapi's guid) by matching on (event_id, draw_number, team involvement).
    A team plays at most one game per draw, so this match is unambiguous.
    """
    conn = sqlite3.connect(DB_PATH)
    create_tables(conn)
    cur = conn.cursor()
    updated = 0
    for s in schedule:
        cur.execute(
            """
            UPDATE games SET cz_game_id = ?
            WHERE event_id = ? AND draw_number = ?
              AND (team1_id = ? OR team2_id = ?)
            """,
            (s["cz_game_id"], event_id, s["draw_number"], team_id, team_id),
        )
        updated += cur.rowcount
    conn.commit()
    conn.close()
    return updated


def save_event_sfm(event_id: int, sfm: str):
    """
    SFM belongs to the `events` table (created by ingest_curling_data.py),
    not a roster_scraper.py table — but roster_scraper.py may run against
    a fresh curling.db that hasn't ingested that event yet, so create the
    table defensively here too, and add the sfm_points column if it's an
    older curling.db that predates this field.
    """
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS events (
            event_id INTEGER PRIMARY KEY,
            event_name TEXT,
            season TEXT
        )
        """
    )
    cur.execute("PRAGMA table_info(events)")
    existing_columns = {row[1] for row in cur.fetchall()}
    if "sfm_points" not in existing_columns:
        cur.execute("ALTER TABLE events ADD COLUMN sfm_points REAL")

    cur.execute(
        """
        INSERT INTO events (event_id, sfm_points)
        VALUES (?, ?)
        ON CONFLICT(event_id) DO UPDATE SET sfm_points = excluded.sfm_points
        """,
        (event_id, sfm),
    )
    conn.commit()
    conn.close()


GAME_URL = "https://www.curlingzone.com/game.php"


def scrape_game_meta(cz_game_id: int) -> dict:
    """
    Scrapes game.php for two things:
    1. Event-level metadata from the og:description meta tag — same on
       EVERY game page for a given event, so this only needs to run once
       per event, not once per game. Gives: dates, venue, location,
       num_teams, format, purse — confirmed via real HTML testing.
    2. This specific draw's date/time, from the "Draw: N -- Day, Date --
       Time TZ" heading on the "Scoreboard: Other Games on Draw" widget.
       Confirmed this SURVIVES after the game completes (doesn't get
       overwritten by the final score) — contrary to what we worried
       about from the team-page schedule table, which DOES get
       overwritten once a game finishes.
    """
    resp = requests.get(GAME_URL, params={"1": "1", "showgameid": cz_game_id}, timeout=10)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    event_meta = {}
    desc_tag = soup.find("meta", property="og:description")
    if desc_tag and desc_tag.get("content"):
        m = re.search(
            r"takes place (?P<dates>.+?) at (?P<venue>.+?) in (?P<location>.+?), "
            r"featuring (?P<num_teams>\d+) teams playing a (?P<format>.+?) format "
            r"for a (?P<purse>.+?) purse",
            desc_tag["content"],
        )
        if m:
            event_meta = m.groupdict()

    draw_date, draw_time = None, None
    draw_anchor = soup.find("a", attrs={"name": re.compile(r"^draw\d+$")})
    if draw_anchor:
        cell_text = draw_anchor.parent.get_text(strip=True)
        parts = [p.strip() for p in re.split(r"--", cell_text)]
        if len(parts) >= 3:
            draw_date, draw_time = parts[1], parts[2]

    return {"cz_game_id": cz_game_id, "event_meta": event_meta, "draw_date": draw_date, "draw_time": draw_time}


def save_game_meta(cz_game_id: int, data: dict):
    conn = sqlite3.connect(DB_PATH)
    create_tables(conn)
    cur = conn.cursor()

    # Find which of our games this cz_game_id belongs to, to get event_id
    # and update this specific game's draw_date/draw_time.
    cur.execute("SELECT event_id FROM games WHERE cz_game_id = ?", (cz_game_id,))
    row = cur.fetchone()
    if row is None:
        conn.close()
        raise ValueError(
            f"No game in the database has cz_game_id={cz_game_id} yet — "
            f"run 'event-team' mode first to bridge the IDs."
        )
    event_id = row[0]

    if data["draw_date"] or data["draw_time"]:
        cur.execute(
            "UPDATE games SET draw_date = ?, draw_time = ? WHERE cz_game_id = ?",
            (data["draw_date"], data["draw_time"], cz_game_id),
        )

    meta = data["event_meta"]
    if meta:
        cur.execute(
            """
            UPDATE events SET venue = ?, location = ?, num_teams = ?, format = ?, purse = ?, dates = ?
            WHERE event_id = ?
            """,
            (
                meta.get("venue"), meta.get("location"),
                int(meta["num_teams"]) if meta.get("num_teams") else None,
                meta.get("format"), meta.get("purse"), meta.get("dates"),
                event_id,
            ),
        )

    conn.commit()
    conn.close()


def print_event_team(data: dict):
    print(f"Event {data['event_id']}, team {data['team_id']}")
    if data.get("sfm"):
        print(f"SFM (ranking points multiplier): {data['sfm']}")
    print("\nRoster:")
    for p in data["players"]:
        print(f"  {p['label'] or '?':<8} {p['name']} (player_id={p['player_id']})")

    print("\nStats:")
    for table_name, stats in data["stats"].items():
        print(f"  --- {table_name} ---")
        for k, v in stats.items():
            print(f"    {k}: {v}")


# ---------- CLI ----------

def print_roster(roster: dict):
    print(f"{roster['team_name']} — {roster['club']}, {roster['country']} ({roster['season']})")
    for p in roster["players"]:
        print(f"  {p['position']:<6} {p['player_name']} (player_id={p['player_id']})")


def print_player_profile(profile: dict):
    print(profile["name"])
    for field in ("age", "born", "resides", "throws", "profession", "high_school"):
        value = profile.get(field)
        if value:
            print(f"  {field.replace('_', ' ').title()}: {value}")


def print_team_history(history: list):
    print(f"\n  Team history ({len(history)} entries):")
    for h in history:
        loc = f" — {h['location']}" if h["location"] else ""
        season = h["season"] or "?"
        discipline = h["discipline"] or "?"
        print(f"    {season:<10} {discipline:<15} team_id={h['team_id']}{loc}")


if __name__ == "__main__":
    if len(sys.argv) < 3 or sys.argv[1] not in ("team", "player", "event-team", "game-meta"):
        print("Usage:")
        print("  py roster_scraper.py team <team_id>")
        print("  py roster_scraper.py player <player_id>")
        print("  py roster_scraper.py event-team <event_id> <team_id>")
        print("  py roster_scraper.py game-meta <cz_game_id>")
        sys.exit(1)

    mode = sys.argv[1]

    if mode == "event-team":
        if len(sys.argv) < 4:
            print("Usage: py roster_scraper.py event-team <event_id> <team_id>")
            sys.exit(1)
        event_id, team_id = int(sys.argv[2]), int(sys.argv[3])
        data = scrape_event_team(event_id, team_id)
        print_event_team(data)
        save_roster(team_id, data["players"], source="event.php")
        if data.get("sfm"):
            save_event_sfm(event_id, data["sfm"])
        n_bridged = save_game_ids(event_id, team_id, data.get("schedule", []))
        print(f"\nSaved {len(data['players'])} roster entries for team_id={team_id}.")
        print(f"Bridged cz_game_id for {n_bridged} games.")
        sys.exit(0)

    if mode == "game-meta":
        if len(sys.argv) < 3:
            print("Usage: py roster_scraper.py game-meta <cz_game_id>")
            sys.exit(1)
        cz_game_id = int(sys.argv[2])
        data = scrape_game_meta(cz_game_id)
        print(f"Event metadata: {data['event_meta']}")
        print(f"Draw date: {data['draw_date']}, time: {data['draw_time']}")
        save_game_meta(cz_game_id, data)
        print("Saved.")
        sys.exit(0)
        sys.exit(0)

    entity_id = int(sys.argv[2])

    if mode == "team":
        roster = scrape_roster(entity_id)
        print_roster(roster)
        save_roster(entity_id, roster["players"], source="team.php")
        print(f"\nSaved {len(roster['players'])} roster entries for team_id={entity_id}.")

        print("\nFetching player profiles...")
        for p in roster["players"]:
            profile = scrape_player_profile(p["player_id"])
            print()
            print_player_profile(profile)
            save_player_profile(profile)

    elif mode == "player":
        profile = scrape_player_profile(entity_id)
        print_player_profile(profile)
        save_player_profile(profile)

        history = scrape_player_team_history(entity_id)
        print_team_history(history)
        save_player_team_history(entity_id, history)
        print(f"\nSaved profile and {len(history)} team-history entries for player_id={entity_id}.")
