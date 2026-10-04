import { useEffect, useState } from "react";
import "./runMap.css";
import { RunReplay } from "./RunReplay";
import type { ReplayData } from "./runReplayData";

type Room = {
  tiles: number[];
  name: string | null;
  type: string;
  state: string;
  secrets_found: number | null;
  secrets_total: number | null;
  elapsed_ms?: number;
  ticks?: number;
};
type RunStats = {
  elapsed_ms: number;
  ticks: number;
  transit_ms: number;
  transit_ticks: number;
  secrets_found: number | null;
  secrets_total: number | null;
  crypts: number | null;
};
type MapData = {
  version: 1 | 2;
  rooms: Room[];
  doors: { a: number; b: number; type: string }[];
  stats?: RunStats;
  replay?: ReplayData;
};
type Run = {
  version: 1;
  record: {
    id: string;
    uuid: string;
    name: string | null;
    floor: string;
    ticks: number;
    created: number;
  };
  map: MapData | null;
};

const colors: Record<string, string> = {
  NORMAL: "#936c4e",
  RARE: "#bf9954",
  ENTRANCE: "#4d9067",
  BLOOD: "#af515e",
  FAIRY: "#cc82b2",
  CHAMPION: "#d6aa57",
  PUZZLE: "#9b7bbb",
  TRAP: "#c5824b",
};
const doorColors: Record<string, string> = {
  WITHER: "#d6b4e8",
  BLOOD: "#f07b87",
};
const markers: Record<string, string> = {
  COMPLETE: "✓",
  CLEARED: "•",
  FAILED: "×",
};
const coordinate = (tile: number) => ({
  x: (tile % 6) * 60 + 10,
  y: Math.floor(tile / 6) * 60 + 10,
});
const label = (value: string) => value.charAt(0) + value.slice(1).toLowerCase();
const count = (room: Room) =>
  `${room.secrets_found ?? "?"}/${room.secrets_total ?? "?"}`;

function time(ticks: number) {
  const ms = ticks * 50;
  return `${Math.floor(ms / 60000)}:${(Math.floor(ms / 1000) % 60).toString().padStart(2, "0")}.${(ms % 1000).toString().padStart(3, "0")}`;
}

export function RunMap({ recordId }: Readonly<{ recordId: string }>) {
  const [run, setRun] = useState<Run | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    const deadline = setTimeout(() => controller.abort(), 5000);
    void fetch(`/api/v1/records/solo/${recordId}`, {
      signal: controller.signal,
      cache: "no-store",
    })
      .then(async (response) => {
        if (!response.ok)
          throw new Error(
            response.status === 404
              ? "This run is unavailable."
              : "Could not load this run. Try again shortly.",
          );
        const value = (await response.json()) as Run;
        if (
          value.version !== 1 ||
          (value.map && ![1, 2].includes(value.map.version))
        )
          throw new Error("This run uses an unsupported map format.");
        if (active) setRun(value);
      })
      .catch((reason: unknown) => {
        if (active)
          setError(
            reason instanceof Error && reason.name !== "AbortError"
              ? reason.message
              : "Could not load this run. Try again shortly.",
          );
      })
      .finally(() => clearTimeout(deadline));
    return () => {
      active = false;
      clearTimeout(deadline);
      controller.abort();
    };
  }, [recordId]);

  if (error)
    return (
      <>
        <title>Run unavailable · Mithril</title>
        <h1>Run unavailable</h1>
        <p role="alert">{error}</p>
      </>
    );
  if (!run) return <output>Loading run…</output>;
  const name = run.record.name || run.record.uuid;
  return (
    <section className="run-page">
      <title>{`${run.record.floor} solo clear · ${name} · Mithril`}</title>
      <p className="eyebrow">{run.record.floor} · Solo clear</p>
      <h1>
        {time(run.record.ticks)} <span className="run-player">by {name}</span>
      </h1>
      <p className="run-caption">
        Snapshot at 300 score ·{" "}
        {new Date(run.record.created * 1000).toLocaleDateString(undefined, {
          year: "numeric",
          month: "long",
          day: "numeric",
        })}
      </p>
      {run.map ? (
        <DungeonMap data={run.map} />
      ) : (
        <div className="run-map-empty">
          <h2>Map unavailable</h2>
          <p>
            Maps are kept only for each player’s current best on each floor.
            This run may predate map capture or have been replaced by a faster
            PB.
          </p>
        </div>
      )}
    </section>
  );
}

function DungeonMap({ data }: Readonly<{ data: MapData }>) {
  const [selected, setSelected] = useState(0);
  const room = data.rooms[selected];
  return (
    <>
      {data.stats ? (
        <>
          <dl className="run-summary" aria-label="Dungeon totals at 300 score">
            <div>
              <dt>Secrets collected</dt>
              <dd>{data.stats.secrets_found ?? "Not captured"}</dd>
            </div>
            <div>
              <dt>Total secrets</dt>
              <dd>{data.stats.secrets_total ?? "Not captured"}</dd>
            </div>
            <div>
              <dt>Crypts killed</dt>
              <dd>{data.stats.crypts ?? "Not captured"}</dd>
            </div>
          </dl>
          <p className="run-timing">
            Rooms{" "}
            <strong>{time(data.stats.ticks - data.stats.transit_ticks)}</strong>
            {" + "}Transit / unmapped{" "}
            <strong>{time(data.stats.transit_ticks)}</strong>
            {" = "}Run <strong>{time(data.stats.ticks)}</strong>
          </p>
          <p className="run-caption">
            Times use server ticks, include repeat visits, and stop at 300
            score.
          </p>
        </>
      ) : (
        <p className="run-caption">
          Room timing and dungeon totals were not recorded for this run.
        </p>
      )}
      <div className="run-map-layout">
        <div className="run-map-canvas">
          <RunReplay data={data.replay}>
            <svg
              viewBox="0 0 370 370"
              role="img"
              aria-label="Dungeon layout at 300 score"
            >
              {data.doors.map((door) => {
                const a = coordinate(door.a),
                  b = coordinate(door.b);
                const horizontal = a.y === b.y;
                return (
                  <line
                    key={`${door.a}-${door.b}`}
                    x1={a.x + 24 + (horizontal ? 24 : 0)}
                    y1={a.y + 24 + (horizontal ? 0 : 24)}
                    x2={b.x + 24 - (horizontal ? 24 : 0)}
                    y2={b.y + 24 - (horizontal ? 0 : 24)}
                    stroke={doorColors[door.type] ?? "#aaa39b"}
                    strokeWidth="8"
                  >
                    <title>{label(door.type)} door</title>
                  </line>
                );
              })}
              {data.rooms.map((entry, index) => (
                <a
                  key={entry.tiles[0]}
                  href="#room-details"
                  onClick={() => setSelected(index)}
                  aria-label={`${entry.name ?? label(entry.type)}: ${count(entry)} secrets`}
                  className={
                    index === selected ? "map-room selected" : "map-room"
                  }
                >
                  <g fill={colors[entry.type] ?? "#68717a"}>
                    {entry.tiles.flatMap((tile) =>
                      entry.tiles
                        .filter(
                          (other) =>
                            other === tile + 6 ||
                            (other === tile + 1 &&
                              Math.floor(other / 6) === Math.floor(tile / 6)),
                        )
                        .map((other) => {
                          const a = coordinate(tile),
                            b = coordinate(other);
                          const square =
                            other === tile + 1 &&
                            entry.tiles.includes(tile + 6) &&
                            entry.tiles.includes(tile + 7);
                          return (
                            <rect
                              key={`${tile}-${other}`}
                              x={a.x}
                              y={a.y}
                              width={b.x - a.x + 48}
                              height={square ? 108 : b.y - a.y + 48}
                            />
                          );
                        }),
                    )}
                    {entry.tiles.map((tile) => {
                      const p = coordinate(tile);
                      return (
                        <rect
                          key={tile}
                          x={p.x}
                          y={p.y}
                          width="48"
                          height="48"
                        />
                      );
                    })}
                  </g>
                  {entry.tiles.slice(0, 1).map((tile) => {
                    const p = coordinate(tile);
                    return (
                      <g key={tile} className="map-room-label">
                        <text x={p.x + 24} y={p.y + 24}>
                          {count(entry)}
                        </text>
                        <text x={p.x + 24} y={p.y + 40} className="map-marker">
                          {markers[entry.state] ?? ""}
                        </text>
                      </g>
                    );
                  })}
                </a>
              ))}
            </svg>
          </RunReplay>
          <p className="run-caption">
            Found / total secrets · ✓ Complete · • Cleared · × Failed
          </p>
        </div>
        <section
          id="room-details"
          className="run-room-details"
          aria-live="polite"
        >
          <p className="eyebrow">Selected room</p>
          <h2>
            {room?.name ??
              (room ? `${label(room.type)} room` : "No rooms captured")}
          </h2>
          {room && (
            <>
              <dl>
                <div>
                  <dt>Type</dt>
                  <dd>{label(room.type)}</dd>
                </div>
                <div>
                  <dt>Status</dt>
                  <dd>{label(room.state)}</dd>
                </div>
                <div>
                  <dt>Time in room</dt>
                  <dd>
                    {room.ticks === undefined
                      ? "Not recorded"
                      : time(room.ticks)}
                  </dd>
                </div>
                <div>
                  <dt>Secrets</dt>
                  <dd>{count(room)}</dd>
                </div>
                <div>
                  <dt>Size</dt>
                  <dd>
                    {room.tiles.length}{" "}
                    {room.tiles.length === 1 ? "tile" : "tiles"}
                  </dd>
                </div>
              </dl>
              {(room.secrets_found === null || room.secrets_total === null) && (
                <p>Part of this room’s secret counter was not captured.</p>
              )}
            </>
          )}
        </section>
      </div>
      <h2>Rooms</h2>
      <div className="run-room-list">
        {data.rooms.map((entry, index) => (
          <button
            type="button"
            key={entry.tiles[0]}
            onClick={() => setSelected(index)}
            aria-pressed={selected === index}
          >
            <span>
              <i
                style={{ background: colors[entry.type] ?? "#68717a" }}
                aria-hidden="true"
              />
              {entry.name ?? `${label(entry.type)} room`}
            </span>{" "}
            <span>
              {entry.ticks !== undefined && (
                <>
                  <strong>{time(entry.ticks)}</strong>
                  {" · "}
                </>
              )}
              {count(entry)} <small>secrets · {label(entry.state)}</small>
            </span>
          </button>
        ))}
      </div>
    </>
  );
}
