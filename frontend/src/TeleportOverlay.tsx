import { replayCoordinate } from "./runReplayData";
import {
  segment,
  teleportBlink,
  teleportColors,
  teleportKinds,
  teleportWindow,
  type TeleportEvent,
} from "./replayTeleports";

export function TeleportOverlay({
  events,
  paths,
  ms,
  speed,
  showRoute,
}: Readonly<{
  events: readonly TeleportEvent[];
  paths: readonly string[];
  ms: number;
  speed: number;
  showRoute: boolean;
}>) {
  return (
    <>
      {showRoute && (
        <g className="replay-route">
          <path d={paths[0]} className="replay-route-walk" />
          {teleportKinds.map((kind) => (
            <path
              key={kind}
              d={paths[kind]}
              className="replay-teleport-path"
              stroke={teleportColors[kind]}
            />
          ))}
        </g>
      )}
      {teleportWindow(events, ms, 3000)
        .filter((e) => !((e.from.flags | e.to.flags) & 2))
        .map((e) => (
          <path
            key={e.to.ms}
            className="replay-teleport-path replay-teleport-trail"
            stroke={teleportColors[e.kind]}
            opacity={0.45 * (1 - (ms - e.to.ms) / 3000)}
            d={segment(e.from, e.to)}
          />
        ))}
      {teleportBlink(events, ms, speed).map((e) => {
        const progress = (ms - e.to.ms) / (400 * speed);
        const x = replayCoordinate(e.to.x),
          y = replayCoordinate(e.to.z);
        return (
          <g
            key={e.to.ms}
            className="replay-teleport-blink"
            stroke={teleportColors[e.kind]}
          >
            {!(e.from.flags & 2) && (
              <>
                <path
                  className="replay-teleport-path"
                  d={segment(e.from, e.to)}
                />
                <circle
                  className="teleport-motion"
                  cx={replayCoordinate(e.from.x)}
                  cy={replayCoordinate(e.from.z)}
                  r={4 + progress * 7}
                  opacity={1 - progress}
                  fill="none"
                />
              </>
            )}
            <circle
              className="teleport-motion"
              cx={x}
              cy={y}
              r={8 * (1 - progress) + 2}
              opacity={1 - progress}
              fill="none"
            />
            <circle
              className="teleport-static"
              cx={x}
              cy={y}
              r="3"
              fill={teleportColors[e.kind]}
            />
            {e.count > 1 && (
              <text
                className="replay-teleport-label"
                x={x + 7}
                y={y - 9}
                fill={teleportColors[e.kind]}
                stroke="none"
              >
                ×{e.count}
                {e.count === 4 ? "+" : ""}
              </text>
            )}
          </g>
        );
      })}
    </>
  );
}
