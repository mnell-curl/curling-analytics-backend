# Curling Analytics Website — Design Doc

*Modeled on Neil Pierre-Louis's guide to building PierreAnalytics (hockey), adapted for curling.*

## Overview / Objective

A full-stack website for exploring curling team and player performance — start with round-robin results and end-by-end scoring, and grow toward shot-level analytics (hammer efficiency, steal rate, shot percentage by position). Build it as a portfolio piece and a way to get real front-end/back-end/database reps in.

## Requirements

- **Data source:** CurlingZone (via the `czapi` scraper) for boxscores; `results.worldcurling.org` for standings/championship history; academic shot-level datasets as a stretch goal.
- **Database:** SQLite to start (low traffic, portable, embedded — same reasoning as the original guide).
- **Backend:** Express.js (Node) or Flask (Python) — pick whichever matches the language you're scraping in, since it saves you a context switch.
- **Hosting:** Start with Heroku or Render for the quick deploy, move to AWS/GCP once you care about uptime and security.

## UI/UX

- **Team/Game card page** — the curling equivalent of Neil's player card: an end-by-end line score, hammer indicator, and a running score chart.
- **"House" view** — a simple SVG of the curling house (the target rings) is the signature visual for this sport, the way the rink/shot chart is for hockey. Even a static rendering of stone positions per end is a strong differentiator.
- **Standings/rankings page** — round-robin standings with win/loss and playoff qualification, similar to the WCF rankings page.
- Accessibility and mobile-friendliness rules from the original guide apply as-is: no red/green gradients, filterable tables, visible nav.

## Timeline/Milestones (example — adjust to your pace)

1. **Week 1–2:** Get `czapi` pulling boxscores for one event; land raw data in SQLite.
2. **Week 3:** Build summary tables (team record, ends won/lost, stolen ends, blank ends).
3. **Week 4–5:** Backend API for team/game cards.
4. **Week 6–8:** Frontend — standings table, team card page, house/end visualization.
5. **Ongoing:** Automate scraping (cron job / Task Scheduler) so results update after each draw.

## Alternatives/Challenges

- CurlingZone has no official public API — the `czapi` package scrapes HTML, so it can break if the site changes. Keep scraping logic isolated from your data model so a break is a small fix, not a rewrite.
- Shot-level data (stone coordinates, individual shot percentage) is much harder to get than end-level scores. Treat it as a v2 goal, not a launch requirement.
- Curling has far fewer live data consumers than hockey/baseball, so expect to do more manual verification against official broadcasts/scoreboards early on.

## Testing

- Validate scraped boxscores against the official results site for a handful of games before trusting the pipeline.
- Check mobile rendering of the house/end visualizations specifically — SVGs at small sizes are easy to get wrong.

---

## Data & Structure

### Data flow

```
CurlingZone (czapi scraper) ─┐
results.worldcurling.org ────┼──> Raw boxscore/standings data
                              │
                              v
                     Preprocessing / cleaning
                   (normalize team & player IDs,
                    parse end-by-end score arrays)
                              │
                              v
                  Summary tables (team record,
                 stolen ends, blank ends, hammer
                    conversion, plus/minus)
                              │
                              v
                      SQLite database
                              │
                              v
                    Express/Flask REST API
                              │
                              v
                        Frontend (React/Vue)
```

### Suggested SQLite schema (starting point)

```sql
CREATE TABLE teams (
  team_id INTEGER PRIMARY KEY,
  skip_name TEXT NOT NULL,
  association TEXT,       -- country/province
  season TEXT
);

CREATE TABLE games (
  game_id INTEGER PRIMARY KEY,
  event_name TEXT,
  draw_number INTEGER,
  date TEXT,
  team1_id INTEGER REFERENCES teams(team_id),
  team2_id INTEGER REFERENCES teams(team_id),
  team1_score INTEGER,
  team2_score INTEGER,
  team1_hammer_start BOOLEAN
);

CREATE TABLE ends (
  end_id INTEGER PRIMARY KEY,
  game_id INTEGER REFERENCES games(game_id),
  end_number INTEGER,
  team1_points INTEGER,   -- 0 if blanked or team2 scored
  team2_points INTEGER,
  hammer_team_id INTEGER REFERENCES teams(team_id)
);

CREATE TABLE team_season_stats (
  team_id INTEGER REFERENCES teams(team_id),
  season TEXT,
  wins INTEGER,
  losses INTEGER,
  stolen_ends INTEGER,
  blanked_ends INTEGER,
  hammer_conversion_pct REAL,
  steal_pct REAL
);
```

Same rule as the original guide applies here: **use team/player IDs as your keys, not names** — skip names can repeat or change spelling across sources.

## Back-End

Same Express pattern as the original guide, adapted to a team/game card endpoint:

```js
app.get("/teams/card", (req, res, next) => {
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
        res.status(400).json({ error: err.message });
        return;
      }
      if (row) {
        res.status(200).json({
          wins: row.wins,
          losses: row.losses,
          stolenEnds: row.stolen_ends,
          blankedEnds: row.blanked_ends,
          hammerConversionPct: row.hammer_conversion_pct,
          stealPct: row.steal_pct,
        });
      }
    }
  );
});
```

Descriptive fields (skip name, association, roster) get their own endpoint, same as Neil's approach — don't repeat static info in every stats call.

## Front-End

Component breakdown for a team/game card page (React/Vue/Angular — pick one, same advice as the original: don't try to jam it into one giant component):

- **Card component** — page shell, pulls in the others.
- **Line score component** — end-by-end score table with hammer indicator per end.
- **House/end visualizer component** — SVG rings showing stone positions for a selected end (start simple: even a "which team scored, how many" annotation on a static house graphic is a good v1).
- **Standings/rankings table component** — sortable, filterable by season/division.
- **Team stats component** — stolen ends, blank ends, hammer conversion, steal %.

## Git

Same workflow as the original guide: branch per feature/issue, commit to master at minimum for the change log, connect to auto-deploy on push. Given the scraper is the most fragile part of this project, keep it in its own module/branch history so you can roll it back independently of frontend/backend changes.

## Resources

- CurlingZone scraper: `pip install czapi` (PyPI)
- World Curling official results: results.worldcurling.org
- WCF World Rankings: en.wikipedia.org/wiki/WCF_World_Rankings
- Mixed doubles shot-level dataset paper (arXiv): "Opening the House: Datasets for Mixed Doubles Curling" — good schema reference for a v2 shot-tracking effort
- Original inspiration/guide: Neil Pierre-Louis, "A Guide to Building Your Own Full-Stack Sports Analytics Website" (Medium)
