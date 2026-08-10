/*
Curling Analytics — Express backend

Setup:
    npm init -y
    npm install express sqlite3

Run:
    node server.js

Endpoints:
    GET /teams/card?id=<team_id>&season=<season>
        -> stats for one team (wins, losses, stolen ends, etc.)

    GET /teams/info?id=<team_id>
        -> static descriptive info (name, association) — separate from stats,
           same principle as the original guide: don't repeat static fields
           in every stats call.

    GET /standings?season=<season>
        -> full standings table for a season, sorted by wins.

    GET /games?team_id=<team_id>&season=<season>
        -> list of games for a team, for a schedule/results view.

    GET /games/:game_id/ends
        -> end-by-end line score for a single game (powers the line-score
           component from the design doc).
*/

const express = require("express");
const sqlite3 = require("sqlite3").verbose();
const cors = require("cors");

const app = express();
const PORT = process.env.PORT || 3000;
const db = new sqlite3.Database("./curling.db");

app.use(cors());
app.use(express.json());

// --- GET /teams/card ---
app.get("/teams/card", (req, res) => {
  const id = req.query.id;
  const season = req.query.season;

  if (!id || !season) {
    return res.status(400).json({ error: "Undefined parameters" });
  }

  db.get(
    `SELECT * FROM team_season_stats WHERE team_id = ? AND season = ?`,
    [id, season],
    (err, row) => {
      if (err) {
        return res.status(500).json({ error: err.message });
      }
      if (!row) {
        return res.status(404).json({ error: "No stats found for that team/season" });
      }

      res.status(200).json({
        wins: row.wins,
        losses: row.losses,
        stolenEnds: row.stolen_ends,
        blankedEnds: row.blanked_ends,
        hammerConversionPct: row.hammer_conversion_pct,
        stealPct: row.steal_pct,
      });
    }
  );
});

// --- GET /teams/info ---
app.get("/teams/info", (req, res) => {
  const id = req.query.id;

  if (!id) {
    return res.status(400).json({ error: "Undefined parameters" });
  }

  db.get(`SELECT * FROM teams WHERE team_id = ?`, [id], (err, row) => {
    if (err) {
      return res.status(500).json({ error: err.message });
    }
    if (!row) {
      return res.status(404).json({ error: "Team not found" });
    }

    res.status(200).json({
      teamId: row.team_id,
      skipName: row.skip_name,
      association: row.association,
      season: row.season,
    });
  });
});

// --- GET /standings ---
app.get("/standings", (req, res) => {
  const season = req.query.season;

  if (!season) {
    return res.status(400).json({ error: "Undefined parameters" });
  }

  db.all(
    `SELECT t.team_id, t.skip_name, t.association, s.wins, s.losses,
            s.stolen_ends, s.blanked_ends, s.hammer_conversion_pct, s.steal_pct
     FROM team_season_stats s
     JOIN teams t ON t.team_id = s.team_id
     WHERE s.season = ?
     ORDER BY s.wins DESC, s.losses ASC`,
    [season],
    (err, rows) => {
      if (err) {
        return res.status(500).json({ error: err.message });
      }

      const standings = rows.map((row) => ({
        teamId: row.team_id,
        skipName: row.skip_name,
        association: row.association,
        wins: row.wins,
        losses: row.losses,
        stolenEnds: row.stolen_ends,
        blankedEnds: row.blanked_ends,
        hammerConversionPct: row.hammer_conversion_pct,
        stealPct: row.steal_pct,
      }));

      res.status(200).json(standings);
    }
  );
});

// --- GET /games ---
app.get("/games", (req, res) => {
  const teamId = req.query.team_id;

  if (!teamId) {
    return res.status(400).json({ error: "Undefined parameters" });
  }

  db.all(
    `SELECT * FROM games WHERE team1_id = ? OR team2_id = ? ORDER BY draw_number ASC`,
    [teamId, teamId],
    (err, rows) => {
      if (err) {
        return res.status(500).json({ error: err.message });
      }

      const games = rows.map((row) => ({
        gameId: row.game_id,
        eventName: row.event_name,
        drawNumber: row.draw_number,
        date: row.date,
        team1Id: row.team1_id,
        team2Id: row.team2_id,
        team1Score: row.team1_score,
        team2Score: row.team2_score,
        team1HammerStart: !!row.team1_hammer_start,
      }));

      res.status(200).json(games);
    }
  );
});

// --- GET /games/:game_id ---
app.get("/games/:game_id", (req, res) => {
  const gameId = req.params.game_id;

  db.get(`SELECT * FROM games WHERE game_id = ?`, [gameId], (err, row) => {
    if (err) {
      return res.status(500).json({ error: err.message });
    }
    if (!row) {
      return res.status(404).json({ error: "Game not found" });
    }

    res.status(200).json({
      gameId: row.game_id,
      eventName: row.event_name,
      drawNumber: row.draw_number,
      date: row.date,
      team1Id: row.team1_id,
      team2Id: row.team2_id,
      team1Score: row.team1_score,
      team2Score: row.team2_score,
      team1HammerStart: !!row.team1_hammer_start,
    });
  });
});

// --- GET /games/:game_id/ends ---
app.get("/games/:game_id/ends", (req, res) => {
  const gameId = req.params.game_id;

  db.all(
    `SELECT * FROM ends WHERE game_id = ? ORDER BY end_number ASC`,
    [gameId],
    (err, rows) => {
      if (err) {
        return res.status(500).json({ error: err.message });
      }
      if (rows.length === 0) {
        return res.status(404).json({ error: "No ends found for that game_id" });
      }

      const ends = rows.map((row) => ({
        endNumber: row.end_number,
        team1Points: row.team1_points,
        team2Points: row.team2_points,
        hammerTeamId: row.hammer_team_id,
      }));

      res.status(200).json(ends);
    }
  );
});

app.listen(PORT, () => {
  console.log(`Curling analytics API running on http://localhost:${PORT}`);
});