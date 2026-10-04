import {
  useEffect,
  useMemo,
  useState,
  type ReactNode,
  type KeyboardEvent,
} from "react";
import {
  replayCoordinate,
  replayIndex,
  replayPosition,
  replayTime,
  replayTrail,
  type ReplayPoint,
  type RoomVisit,
} from "./runReplayData";

export function RunReplay({
  points,
  visits,
  rooms,
  children,
  ms,
  setMs,
  playing,
  setPlaying,
  onFollow,
}: Readonly<{
  points: readonly ReplayPoint[];
  visits: readonly RoomVisit[];
  rooms: readonly { name: string; color: string }[];
  children: ReactNode;
  ms: number;
  setMs: React.Dispatch<React.SetStateAction<number>>;
  playing: boolean;
  setPlaying: (value: boolean) => void;
  onFollow: () => void;
}>) {
  const [speed, setSpeed] = useState(2);
  const [hoverMs, setHoverMs] = useState<number | null>(null);
  const duration = points.at(-1)?.ms ?? 0;
  const events = useMemo(
    () =>
      points.flatMap((point, index) => {
        const gained = point.secrets - (points[index - 1]?.secrets ?? 0);
        return gained > 0 ? [{ ...point, gained }] : [];
      }),
    [points],
  );
  useEffect(() => {
    if (!playing) return;
    let frame = 0,
      previous = performance.now();
    const advance = (now: number) => {
      const delta = now - previous;
      previous = now;
      setMs((value) => Math.min(duration, value + delta * speed));
      frame = requestAnimationFrame(advance);
    };
    frame = requestAnimationFrame(advance);
    return () => cancelAnimationFrame(frame);
  }, [playing, duration, setMs, speed]);
  useEffect(() => {
    if (ms >= duration && playing) setPlaying(false);
  }, [ms, duration, playing, setPlaying]);
  if (!points.length) return children;
  const player = replayPosition(points, ms);
  const event = events[replayIndex(events, ms)];
  const flash = event && ms - event.ms < 1500 && !(event.flags & 2);
  const observed = points[replayIndex(points, ms)]?.secrets ?? 0;
  const toggle = () => {
    if (!playing) {
      if (ms >= duration) setMs(0);
      onFollow();
    }
    setPlaying(!playing);
  };
  const seek = (value: number) => {
    setPlaying(false);
    onFollow();
    setMs(Math.max(0, Math.min(duration, value)));
  };
  const keyboard = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.altKey || e.ctrlKey || e.metaKey) return;
    if (e.key === " " && (e.target as HTMLElement).closest("button")) return;
    if (e.key === " ") toggle();
    else if (e.key === "ArrowLeft") seek(ms - 5000);
    else if (e.key === "ArrowRight") seek(ms + 5000);
    else if (e.key === "Home") seek(0);
    else if (e.key === "End") seek(duration);
    else return;
    e.preventDefault();
  };
  const trail = replayTrail(points, ms);
  const hovered =
    hoverMs === null
      ? undefined
      : visits.find((v) => v.start <= hoverMs && hoverMs < v.end);
  const hoverLabel = hovered
    ? `${rooms[hovered.room]!.name} · ${replayTime(hovered.start)} – ${replayTime(hovered.end)}`
    : "Transit / unmapped";
  return (
    <div
      className="run-replay"
      role="group"
      aria-label="Run replay"
      tabIndex={0}
      onKeyDown={keyboard}
    >
      <div className="run-map-graphic">
        {children}
        <svg
          className="run-replay-overlay"
          viewBox="0 0 370 370"
          aria-hidden="true"
        >
          {trail.slice(1).map((point, index) => {
            const previous = trail[index]!;
            if (point.flags & 3 || previous.flags & 2 || point.ms <= ms - 3000)
              return null;
            return (
              <polyline
                key={`${point.ms}-${index}`}
                className="replay-trail"
                opacity={Math.max(0.05, 0.65 * (1 - (ms - point.ms) / 3000))}
                points={`${replayCoordinate(previous.x)},${replayCoordinate(previous.z)} ${replayCoordinate(point.x)},${replayCoordinate(point.z)}`}
              />
            );
          })}
          {flash && (
            <g
              transform={`translate(${replayCoordinate(event.x)} ${replayCoordinate(event.z)})`}
            >
              <circle r="12" className="replay-secret" />
              <text y="-17" className="replay-secret-label">
                +{event.gained} secret{event.gained === 1 ? "" : "s"}
              </text>
            </g>
          )}
          {player && (
            <g
              transform={`translate(${replayCoordinate(player.x)} ${replayCoordinate(player.z)}) rotate(${player.yaw + 180})`}
            >
              <path d="M 0 -9 L 6 6 L 0 3 L -6 6 Z" className="replay-player" />
            </g>
          )}
        </svg>
      </div>
      <div className="run-replay-controls">
        <div className="run-replay-bar">
          <button type="button" onClick={toggle}>
            {playing ? "Pause replay" : "Play replay"}
          </button>
          <span className="run-replay-clock">
            {replayTime(ms)} <span>/ {replayTime(duration)}</span>
          </span>
          <div className="run-speed" role="group" aria-label="Playback speed">
            {[1, 2, 4, 8].map((value) => (
              <button
                type="button"
                key={value}
                aria-pressed={speed === value}
                onClick={() => setSpeed(value)}
              >
                {value}×
              </button>
            ))}
          </div>
        </div>
        <div className="run-timeline" onPointerLeave={() => setHoverMs(null)}>
          <div className="run-timeline-track" aria-hidden="true">
            {visits.map((visit, index) => (
              <span
                key={index}
                className="run-visit"
                style={{
                  left: `${(visit.start / duration) * 100}%`,
                  width: `${((visit.end - visit.start) / duration) * 100}%`,
                  background: rooms[visit.room]!.color,
                }}
              />
            ))}
            {events.map((point) => (
              <i
                key={point.ms}
                className="run-secret-tick"
                style={{ left: `${(point.ms / duration) * 100}%` }}
              />
            ))}
            <span
              className="run-playhead"
              style={{ left: `${(ms / duration) * 100}%` }}
            />
          </div>
          <input
            type="range"
            min="0"
            max={duration}
            step="1"
            value={Math.floor(ms)}
            aria-label="Replay position"
            aria-valuetext={`${replayTime(ms)} of ${replayTime(duration)}`}
            aria-keyshortcuts="Space ArrowLeft ArrowRight Home End"
            title={hoverLabel}
            onPointerMove={(e) => {
              const rect = e.currentTarget.getBoundingClientRect();
              setHoverMs(
                Math.max(
                  0,
                  Math.min(
                    duration,
                    ((e.clientX - rect.left) / rect.width) * duration,
                  ),
                ),
              );
            }}
            onChange={(e) => seek(Number(e.target.value))}
          />
          {hoverMs !== null && (
            <span className="run-timeline-tooltip" role="tooltip">
              {hoverLabel}
            </span>
          )}
        </div>
        <p className="run-replay-observed">
          {observed} secrets observed{!player && " · Position not captured"}
        </p>
      </div>
    </div>
  );
}
