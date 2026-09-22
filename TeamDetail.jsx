import { useState, useEffect } from "react";
import GamePicker from "./GamePicker";

const API_BASE = "http://localhost:3000";

function StatBlock({ label, value, colorClass }) {
  return (
    <div className="flex-1 min-w-[110px]">
      <div className="text-xs text-slate-500 uppercase tracking-wide mb-1">{label}</div>
      <div className={`text-2xl font-mono font-medium ${colorClass}`}>{value}</div>
    </div>
  );
}

function BigStatBar({ label, value }) {
  return (
    <div className="mb-3">
      <div className="flex items-baseline justify-between mb-1">
        <span className="text-xs text-slate-400">{label}</span>
        <span className="text-sm font-mono text-slate-200">{value.toFixed(1)}%</span>
      </div>
      <div className="w-full h-2 bg-slate-800 rounded-full overflow-hidden">
        <div
          className="h-full bg-sky-400 rounded-full"
          style={{ width: `${Math.min(value, 100)}%` }}
        />
      </div>
    </div>
  );
}

function RosterList({ roster }) {
  if (!roster || roster.length === 0) return null;

  return (
    <div className="w-full bg-slate-900 rounded-xl border border-slate-700 p-5">
      <h3 className="text-sm font-semibold text-slate-100 mb-3">Roster</h3>
      <div className="flex flex-wrap gap-4">
        {roster.map((p) => (
          <div key={p.playerId} className="min-w-[140px]">
            <div className="text-xs text-slate-500 uppercase tracking-wide">{p.label}</div>
            <div className="text-sm font-medium text-slate-100">{p.name || `Player ${p.playerId}`}</div>
            {p.age && <div className="text-xs text-slate-400">Age {p.age}{p.throws ? ` · ${p.throws}` : ""}</div>}
            {p.born && <div className="text-xs text-slate-500">{p.born}</div>}
          </div>
        ))}
      </div>
    </div>
  );
}

export default function TeamDetail({ teamId, season, eventId, onSelectGame, selectedGameId }) {
  const [info, setInfo] = useState(null);
  const [stats, setStats] = useState(null);
  const [roster, setRoster] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!teamId || !season) return;

    setLoading(true);
    setError(null);

    Promise.all([
      fetch(`${API_BASE}/teams/info?id=${teamId}`).then((r) => {
        if (!r.ok) throw new Error(`Team info failed: ${r.status}`);
        return r.json();
      }),
      fetch(`${API_BASE}/teams/card?id=${teamId}&season=${season}`).then((r) => {
        if (!r.ok) throw new Error(`Team stats failed: ${r.status}`);
        return r.json();
      }),
      // Roster is optional — not every team_id has been scraped yet via
      // roster_scraper.py, so a 404 here shouldn't break the whole page.
      fetch(`${API_BASE}/teams/roster?id=${teamId}`)
        .then((r) => (r.ok ? r.json() : null))
        .catch(() => null),
    ])
      .then(([infoData, statsData, rosterData]) => {
        setInfo(infoData);
        setStats(statsData);
        setRoster(rosterData);
        setLoading(false);
      })
      .catch((err) => {
        setError(err.message);
        setLoading(false);
      });
  }, [teamId, season]);

  if (!teamId) return null;
  if (loading) return <p style={{ color: "white" }}>Loading team details...</p>;
  if (error) return <p style={{ color: "salmon" }}>Error: {error}</p>;

  return (
    <div className="w-full flex flex-col gap-4">
      <div className="w-full bg-slate-900 rounded-xl border border-slate-700 p-5">
        <div className="flex items-baseline justify-between mb-4">
          <h2 className="text-xl font-semibold text-slate-100">{info.skipName}</h2>
          <span className="text-sm font-mono text-slate-400">
            {stats.wins}–{stats.losses}
          </span>
        </div>

        <div className="flex flex-wrap gap-6 mb-5">
          <StatBlock label="Stolen Ends" value={stats.stolenEnds} colorClass="text-amber-400" />
          <StatBlock label="Blanked Ends" value={stats.blankedEnds} colorClass="text-slate-300" />
          <StatBlock
            label="Win %"
            value={`${((stats.wins / (stats.wins + stats.losses)) * 100).toFixed(0)}%`}
            colorClass="text-emerald-400"
          />
        </div>

        <BigStatBar label="Hammer Conversion" value={stats.hammerConversionPct} />
        <BigStatBar label="Steal %" value={stats.stealPct} />
      </div>

      <RosterList roster={roster} />

      <GamePicker
        teamId={teamId}
        teamName={info.skipName}
        eventId={eventId}
        onSelectGame={onSelectGame}
        selectedGameId={selectedGameId}
      />
    </div>
  );
}

/*
NOTES:

- This combines two API calls (/teams/info and /teams/card) with
  Promise.all since neither depends on the other, then reuses the
  existing GamePicker component underneath rather than duplicating
  its games-list logic.

- BigStatBar is basically StandingsTable's StatBar, but bigger and
  labeled — a table row has to be compact, but a dedicated detail
  page has room to make the same information more readable.

- Win % is computed on the fly here (wins / (wins+losses)) rather
  than stored in the database, since it's fully derivable from data
  we already have — no reason to duplicate it as a stored column.
*/
