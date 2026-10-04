import { useEffect, useMemo, useState, type ReactNode } from "react";
import {
  decodeReplay,
  replayCoordinate,
  replayIndex,
  replayPosition,
  replayTime,
  type ReplayData,
} from "./runReplayData";

export function RunReplay({
  data,
  children,
  ms,
  setMs,
}: Readonly<{
  data?: ReplayData;
  children: ReactNode;
  ms: number;
  setMs: React.Dispatch<React.SetStateAction<number>>;
}>) {
  const points = useMemo(() => (data ? decodeReplay(data) : []), [data]);
  const events = useMemo(
    () =>
      points.flatMap((point, index) => {
        const gained = point.secrets - (points[index - 1]?.secrets ?? 0);
        return gained > 0 ? [{ ...point, gained }] : [];
      }),
    [points],
  );
  const [playing, setPlaying] = useState(false);
  const duration = points.at(-1)?.ms ?? 0;
  useEffect(() => {
    if (!playing) return;
    let frame = 0;
    let previous = performance.now();
    const advance = (now: number) => {
      const delta = now - previous;
      previous = now;
      setMs((value) => Math.min(duration, value + delta));
      frame = requestAnimationFrame(advance);
    };
    frame = requestAnimationFrame(advance);
    return () => cancelAnimationFrame(frame);
  }, [playing, duration, setMs]);
  useEffect(() => {
    if (ms >= duration && playing) setPlaying(false);
  }, [ms, duration, playing]);
  if (!data) return children;
  const player = replayPosition(points, ms);
  const event = events[replayIndex(events, ms)];
  const flash = event && ms - event.ms < 1500 && !(event.flags & 2);
  const observed = points[replayIndex(points, ms)]?.secrets ?? 0;
  const playLabel = ms >= duration ? "Replay again" : "Play replay";
  return (
    <>
      <div className="run-map-graphic">
        {children}
        <svg
          className="run-replay-overlay"
          viewBox="0 0 370 370"
          aria-hidden="true"
        >
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
          <button
            type="button"
            onClick={() => {
              if (ms >= duration) setMs(0);
              setPlaying(!playing);
            }}
          >
            {playing ? "Pause replay" : playLabel}
          </button>
          <span>
            {replayTime(ms)} / {replayTime(duration)}
          </span>
        </div>
        <label>
          <span className="sr-only">Replay position</span>
          <input
            type="range"
            min="0"
            max={duration}
            step="1"
            value={Math.floor(ms)}
            aria-label="Replay position"
            aria-valuetext={`${replayTime(ms)} of ${replayTime(duration)}`}
            onChange={(e) => {
              setPlaying(false);
              setMs(Number(e.target.value));
            }}
          />
        </label>
        <p className="run-caption">
          {observed} secrets observed{!player && " · Position not captured"}
        </p>
        <p className="run-caption">
          Elapsed time · Secret indicators are approximate.{" "}
          {data.room_secrets === undefined
            ? "Room counts and states are from 300 score; this replay has no room-counter timeline."
            : "Room secrets follow recorded counter updates. Room states are from 300 score."}
        </p>
      </div>
    </>
  );
}
