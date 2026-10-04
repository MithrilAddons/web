import { useEffect, useMemo, useState } from "react";
import "./runMap.css";
import { RunReplay } from "./RunReplay";
import {
  decodeRoomSecrets,
  decodeReplay,
  replayTile,
  replayPosition,
  replayVisits,
  compactTime,
  replayTime,
  type RoomVisit,
  replayRoomSecrets,
  type ReplayData,
} from "./runReplayData";

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
  const points = useMemo(
    () => (data.replay ? decodeReplay(data.replay) : []),
    [data.replay],
  );
  const duration = points.at(-1)?.ms ?? 0;
  const tiles = useMemo(
    () =>
      new Map(
        data.rooms.flatMap((r, i) => r.tiles.map((tile) => [tile, i] as const)),
      ),
    [data.rooms],
  );
  const visits = useMemo(() => replayVisits(points, tiles), [points, tiles]);
  const byRoom = useMemo(
    () => data.rooms.map((_, i) => visits.filter((v) => v.room === i)),
    [data.rooms, visits],
  );
  const initial = useMemo(() => {
    const hash = window.location.hash;
    const room = /^#room-(\d+)$/.exec(hash);
    const moment = /^#t=(\d+(?:\.\d+)?)$/.exec(hash);
    return {
      selected: room
        ? data.rooms.findIndex((r) => r.tiles[0] === Number(room[1]))
        : -1,
      ms: moment ? Math.min(duration, Number(moment[1]) * 1000) : duration,
      follow: !!moment,
    };
  }, [data.rooms, duration]);
  const [manual, setManual] = useState(initial.selected);
  const [ms, setMs] = useState(initial.ms);
  const [following, setFollowing] = useState(initial.follow);
  const [playing, setPlaying] = useState(false);
  const [fromList, setFromList] = useState(false);
  const [sort, setSort] = useState("entry");
  const tile = replayTile(replayPosition(points, ms));
  const playerRoom = tile === null ? -1 : (tiles.get(tile) ?? -1);
  const selected = following ? playerRoom : manual;
  const roomSecrets = useMemo(
    () => decodeRoomSecrets(data.replay),
    [data.replay],
  );
  const final = !points.length || ms >= duration;
  const found = (entry: Room) =>
    final || roomSecrets === null
      ? entry.secrets_found
      : replayRoomSecrets(roomSecrets, entry.tiles[0]!, ms);
  const count = (entry: Room) =>
    `${found(entry) ?? "?"}/${entry.secrets_total ?? "?"}`;
  const reached = (index: number) =>
    final || (byRoom[index]?.[0]?.start ?? Infinity) <= ms;
  const settled = (index: number) =>
    final ||
    (reached(index) &&
      ((roomSecrets !== null &&
        (data.rooms[index]!.secrets_found ?? 0) > 0 &&
        found(data.rooms[index]!) === data.rooms[index]!.secrets_found) ||
        (byRoom[index]?.at(-1)?.end ?? Infinity) <= ms));
  const state = (index: number) => {
    if (settled(index)) return label(data.rooms[index]!.state);
    return reached(index) ? "Visited" : "Not reached";
  };
  const replaceHash = (hash: string) =>
    window.history.replaceState(
      window.history.state,
      "",
      `${window.location.pathname}${window.location.search}${hash}`,
    );
  useEffect(() => {
    if (following && !playing) replaceHash(`#t=${Math.floor(ms) / 1000}`);
  }, [ms, following, playing]);
  const selectRoom = (index: number, seek: boolean, inline = seek) => {
    setManual(index);
    setFollowing(false);
    setFromList(inline);
    if (seek) {
      setPlaying(false);
      const first = byRoom[index]?.[0];
      if (first) setMs(first.start);
    }
    replaceHash(`#room-${data.rooms[index]!.tiles[0]}`);
  };
  const onFollow = () => {
    setFollowing(true);
    setFromList(false);
  };
  const order = useMemo(
    () =>
      data.rooms
        .map((_, i) => i)
        .sort(
          (a, b) =>
            (byRoom[a]?.[0]?.start ?? Infinity) -
              (byRoom[b]?.[0]?.start ?? Infinity) || a - b,
        ),
    [data.rooms, byRoom],
  );
  const sorted = [...order].sort((a, b) =>
    sort === "time"
      ? (data.rooms[b]!.ticks ?? -1) - (data.rooms[a]!.ticks ?? -1)
      : 0,
  );
  const slowest = Math.max(1, ...data.rooms.map((r) => r.ticks ?? 0));
  const details = (index: number) => (
    <RoomDetails
      room={data.rooms[index]!}
      visits={points.length ? byRoom[index]! : null}
      count={count(data.rooms[index]!)}
      state={state(index)}
      runTicks={data.stats?.ticks}
      seek={() => selectRoom(index, true, fromList)}
    />
  );
  return (
    <>
      {data.stats ? (
        <dl className="run-summary" aria-label="Dungeon totals at 300 score">
          <div>
            <dt>Secrets</dt>
            <dd>
              {data.stats.secrets_found ?? "?"}
              <span> / {data.stats.secrets_total ?? "?"}</span>
            </dd>
            <progress
              aria-label="Secrets collected"
              value={data.stats.secrets_found ?? 0}
              max={data.stats.secrets_total || 1}
            />
            {(data.stats.secrets_found === null ||
              data.stats.secrets_total === null) && <small>Not captured</small>}
          </div>
          <div>
            <dt>Crypts killed</dt>
            <dd>{data.stats.crypts ?? "Not captured"}</dd>
          </div>
          <div className="run-split">
            <dt>Time split</dt>
            <dd>
              <span>
                Rooms{" "}
                <strong>
                  {compactTime(
                    (data.stats.ticks - data.stats.transit_ticks) * 50,
                  )}
                </strong>
              </span>
              <span>
                Transit{" "}
                <strong>{compactTime(data.stats.transit_ticks * 50)}</strong>
              </span>
            </dd>
            <div className="run-split-bar" aria-label="Room and transit time">
              <span
                style={{
                  width: `${data.stats.ticks ? ((data.stats.ticks - data.stats.transit_ticks) / data.stats.ticks) * 100 : 0}%`,
                }}
              />
            </div>
          </div>
        </dl>
      ) : (
        <p className="run-caption">
          Room timing and dungeon totals were not recorded for this run.
        </p>
      )}
      <div className={`run-map-layout${fromList ? " list-selection" : ""}`}>
        <div className="run-map-canvas">
          <RunReplay
            points={points}
            visits={visits}
            rooms={data.rooms.map((r) => ({
              name: roomName(r),
              color: colors[r.type] ?? "#68717a",
            }))}
            ms={ms}
            setMs={setMs}
            playing={playing}
            setPlaying={setPlaying}
            onFollow={onFollow}
          >
            <svg
              viewBox="0 0 370 370"
              role="graphics-document"
              aria-label="Dungeon layout at 300 score"
              className={selected >= 0 ? "has-selection" : ""}
            >
              <defs>
                <filter
                  id="room-outline"
                  x="-20%"
                  y="-20%"
                  width="140%"
                  height="140%"
                >
                  <feMorphology
                    in="SourceAlpha"
                    operator="dilate"
                    radius="2"
                    result="expanded"
                  />
                  <feFlood floodColor="#edf5ff" />
                  <feComposite in2="expanded" operator="in" />
                  <feMerge>
                    <feMergeNode />
                    <feMergeNode in="SourceGraphic" />
                  </feMerge>
                </filter>
              </defs>
              {data.doors.map((door) => {
                const a = coordinate(door.a),
                  b = coordinate(door.b),
                  horizontal = a.y === b.y;
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
                <g
                  key={entry.tiles[0]}
                  role="button"
                  tabIndex={0}
                  onClick={() => selectRoom(index, false)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      e.stopPropagation();
                      selectRoom(index, false);
                    }
                  }}
                  aria-label={`${roomName(entry)}: ${reached(index) ? count(entry) + " secrets" : "not reached"}`}
                  aria-pressed={index === selected}
                  className={`map-room${index === selected ? " selected" : ""}${!reached(index) ? " unreached" : ""}`}
                >
                  <title>
                    {roomName(entry)} ·{" "}
                    {entry.ticks === undefined
                      ? "Time not recorded"
                      : compactTime(entry.ticks * 50)}{" "}
                    ·{" "}
                    {reached(index) ? count(entry) + " secrets" : "Not reached"}
                  </title>
                  <g
                    className="map-room-shape"
                    fill={colors[entry.type] ?? "#68717a"}
                  >
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
                  {reached(index) &&
                    entry.tiles.slice(0, 1).map((tile) => {
                      const p = coordinate(tile);
                      return (
                        <g
                          key={tile}
                          className={`map-room-label${entry.secrets_total !== null && entry.secrets_total > 0 && found(entry) === entry.secrets_total ? " all-secrets" : ""}`}
                        >
                          <text x={p.x + 24} y={p.y + 24}>
                            {count(entry)}
                          </text>
                          {settled(index) && (
                            <text
                              x={p.x + 24}
                              y={p.y + 40}
                              className="map-marker"
                            >
                              {markers[entry.state] ?? ""}
                            </text>
                          )}
                        </g>
                      );
                    })}
                </g>
              ))}
            </svg>
          </RunReplay>
          <div className="run-legend" aria-label="Map legend">
            <span>✓ Complete</span>
            <span>• Cleared</span>
            <span>× Failed</span>
            {Object.entries(colors)
              .filter(([type]) => data.rooms.some((r) => r.type === type))
              .map(([type, color]) => (
                <span key={type}>
                  <i style={{ background: color }} />
                  {label(type)}
                </span>
              ))}
          </div>
        </div>
        <section className="run-room-details" aria-label="Room details">
          {selected >= 0 ? (
            details(selected)
          ) : (
            <>
              <p className="eyebrow">300-score snapshot</p>
              <h2>Run summary</h2>
              <p>
                {data.rooms.length} rooms
                {data.stats && <> · {compactTime(data.stats.ticks * 50)}</>}
              </p>
              <p>
                Select a room to inspect it
                {points.length > 0 &&
                  ", or play the replay to follow your route"}
                .
              </p>
              {following && (
                <p className="run-caption">Transit / unmapped position</p>
              )}
            </>
          )}
        </section>
      </div>
      <div className="run-rooms-heading">
        <h2>Rooms</h2>
        <label>
          Sort by{" "}
          <select value={sort} onChange={(e) => setSort(e.target.value)}>
            <option value="entry">Entry order</option>
            <option value="time">Time (slowest first)</option>
          </select>
        </label>
      </div>
      <div className="run-room-list" aria-label="Room breakdown">
        <div className="run-room-columns" aria-hidden="true">
          <span>#</span>
          <span>Room</span>
          <span>Time</span>
          <span>Secrets</span>
          <span>State</span>
        </div>
        {sorted.map((index) => {
          const entry = data.rooms[index]!;
          return (
            <div className="run-room-row" key={entry.tiles[0]}>
              <button
                type="button"
                aria-pressed={selected === index}
                className="run-room-columns"
                onClick={() => selectRoom(index, true)}
                aria-label={`${roomName(entry)}, ${entry.ticks === undefined ? "time not recorded" : compactTime(entry.ticks * 50)}, ${reached(index) ? count(entry) + " secrets" : "not reached"}, ${state(index)}`}
              >
                <span className="run-entry">
                  {byRoom[index]?.length ? order.indexOf(index) + 1 : "—"}
                </span>
                <span className="run-room-name">
                  <i
                    style={{ background: colors[entry.type] ?? "#68717a" }}
                    aria-hidden="true"
                  />
                  {roomName(entry)}
                </span>
                <span className="run-room-time">
                  <span>
                    {entry.ticks === undefined
                      ? "—"
                      : compactTime(entry.ticks * 50)}
                  </span>
                  <i
                    style={{
                      width: `${((entry.ticks ?? 0) / slowest) * 100}%`,
                    }}
                  />
                </span>
                <span>{reached(index) ? count(entry) : "—"}</span>
                <span className="run-state">{state(index)}</span>
              </button>
              {selected === index && fromList && (
                <section
                  className="run-inline-details"
                  aria-label={`${roomName(entry)} details`}
                >
                  {details(index)}
                </section>
              )}
            </div>
          );
        })}
      </div>
      <details className="run-data-notes">
        <summary>About this data</summary>
        <p>
          Times use server ticks, include repeat visits, and stop at 300 score.
          Transit includes doorways and unmapped positions. Room and transit
          times add up to the PB.
        </p>
        {data.replay && (
          <>
            <p>
              Replay uses elapsed time. Secret indicators are approximate.{" "}
              {data.replay.room_secrets === undefined
                ? "Room counts are from 300 score; this replay has no room-counter timeline."
                : "Room secrets follow recorded counter updates."}
            </p>
            <p>
              Entries, visits and room reveals are inferred from sampled
              positions. Markers show the final room state after its final
              recorded secret count or last observed visit; they are not
              recorded clear events. Unobserved rooms remain hidden until the
              final snapshot.
            </p>
            <p>
              With replay focus: Space plays or pauses; ← / → skip 5 seconds;
              Home / End jump to the start / finish. Select a map room to
              inspect without seeking, or a list row to jump to its first entry.
              Play or scrub to resume following. Paused seeks can be shared
              using the time in the URL.
            </p>
          </>
        )}
      </details>
    </>
  );
}

const roomName = (room: Room) => room.name ?? `${label(room.type)} room`;
function RoomDetails({
  room,
  visits,
  count,
  state,
  runTicks,
  seek,
}: Readonly<{
  room: Room;
  visits: RoomVisit[] | null;
  count: string;
  state: string;
  runTicks?: number;
  seek: () => void;
}>) {
  return (
    <>
      <p className="eyebrow">Selected room</p>
      <h2>{roomName(room)}</h2>
      <dl>
        <div>
          <dt>Type</dt>
          <dd>{label(room.type)}</dd>
        </div>
        <div>
          <dt>Status</dt>
          <dd>{state}</dd>
        </div>
        <div>
          <dt>Time in room</dt>
          <dd>
            {room.ticks === undefined
              ? "Not recorded"
              : compactTime(room.ticks * 50)}
          </dd>
        </div>
        <div>
          <dt>Secrets</dt>
          <dd>{count}</dd>
        </div>
        <div>
          <dt>Entered at</dt>
          <dd>
            {visits?.[0] ? (
              <button className="run-seek-link" type="button" onClick={seek}>
                {replayTime(visits[0].start)}
              </button>
            ) : (
              "Not recorded"
            )}
          </dd>
        </div>
        <div>
          <dt>Visits</dt>
          <dd>{visits ? visits.length : "Not recorded"}</dd>
        </div>
        <div>
          <dt>Share of run</dt>
          <dd>
            {runTicks && room.ticks !== undefined
              ? `${((room.ticks / runTicks) * 100).toFixed(1)}%`
              : "Not recorded"}
          </dd>
        </div>
        {(room.secrets_total ?? 0) > 0 && (
          <div>
            <dt>Secrets per minute</dt>
            <dd>
              {room.ticks && room.secrets_found !== null
                ? ((room.secrets_found * 1200) / room.ticks).toFixed(1)
                : "—"}
            </dd>
          </div>
        )}
      </dl>
      {(room.secrets_found === null || room.secrets_total === null) && (
        <p>Part of this room’s secret counter was not captured.</p>
      )}
    </>
  );
}
