import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type PointerEvent as ReactPointerEvent,
  type WheelEvent as ReactWheelEvent,
} from "react";
import type { World } from "./locationsApi";

export type View = { scale: number; x: number; y: number };
type Point = [number, number];

const MAX_SCALE = 8;
const CLICK_SLOP = 5;

/** The whole map centred in a box of the given size. */
export function fit(world: World, width: number, height: number): View {
  const scale = Math.min(width / world.width, height / world.height);
  return {
    scale,
    x: (width - world.width * scale) / 2,
    y: (height - world.height * scale) / 2,
  };
}

/** Zooms by `factor` around a point of the box, between the fitted size and 8×. */
export function zoom(
  view: View,
  factor: number,
  at: Point,
  smallest: number,
): View {
  const scale = Math.max(smallest, Math.min(MAX_SCALE, view.scale * factor));
  const ratio = scale / view.scale;
  return {
    scale,
    x: at[0] - (at[0] - view.x) * ratio,
    y: at[1] - (at[1] - view.y) * ratio,
  };
}

/** A point of the box in world blocks. */
export function toWorld(world: World, view: View, at: Point): Point {
  return [
    Math.round(world.x + (at[0] - view.x) / view.scale),
    Math.round(world.z + (at[1] - view.y) / view.scale),
  ];
}

/** A view showing every point, zoomed in no further than 2×. */
export function frame(
  world: World,
  points: Point[],
  width: number,
  height: number,
): View {
  const xs = points.map((point) => point[0] - world.x);
  const zs = points.map((point) => point[1] - world.z);
  const spanX = Math.max(...xs) - Math.min(...xs) + 120;
  const spanZ = Math.max(...zs) - Math.min(...zs) + 120;
  const scale = Math.min(2, width / spanX, height / spanZ);
  const middleX = (Math.max(...xs) + Math.min(...xs)) / 2;
  const middleZ = (Math.max(...zs) + Math.min(...zs)) / 2;
  return {
    scale,
    x: width / 2 - middleX * scale,
    y: height / 2 - middleZ * scale,
  };
}

/** The combined island map: drag to pan, wheel or pinch to zoom, click to place the pin. */
export function WorldMap({
  world,
  pin,
  answer,
  onPin,
  opponent,
}: Readonly<{
  world: World;
  pin: Point | null;
  answer?: Point | null;
  onPin?: (point: Point) => void;
  /** The other duellist's pin, shown once a round is revealed. */
  opponent?: { pin: Point | null; name: string } | null;
}>) {
  const box = useRef<HTMLDivElement>(null);
  const [view, setView] = useState<View | null>(null);
  const smallest = useRef(0.1);
  const pointers = useRef(new Map<number, Point>());
  const drag = useRef<{ start: Point; moved: boolean } | null>(null);

  const local = useCallback((event: { clientX: number; clientY: number }) => {
    const rect = box.current?.getBoundingClientRect();
    return [
      event.clientX - (rect?.left ?? 0),
      event.clientY - (rect?.top ?? 0),
    ] as Point;
  }, []);

  // Only a new map or a reveal reframes; placing the pin keeps the player's view.
  const pinned = useRef([pin, opponent?.pin ?? null]);
  pinned.current = [pin, opponent?.pin ?? null];
  useLayoutEffect(() => {
    const element = box.current;
    if (!element) return;
    const reframe = () => {
      const width = element.clientWidth || 1;
      const height = element.clientHeight || 1;
      const fitted = fit(world, width, height);
      smallest.current = fitted.scale;
      if (!answer) {
        setView(fitted);
        return;
      }
      const guesses = pinned.current.filter((point): point is Point => !!point);
      setView(frame(world, [...guesses, answer], width, height));
    };
    reframe();
    // A resized panel (a turned phone, the sheet opening) shows the whole map again.
    const observer = new ResizeObserver(reframe);
    observer.observe(element);
    return () => observer.disconnect();
  }, [world, answer]);

  useEffect(() => {
    const element = box.current;
    if (!element) return;
    // Wheel zooming must not scroll the page, so it needs a non-passive listener.
    const stop = (event: WheelEvent) => event.preventDefault();
    element.addEventListener("wheel", stop, { passive: false });
    return () => element.removeEventListener("wheel", stop);
  }, []);

  const onWheel = (event: ReactWheelEvent) => {
    if (!view) return;
    setView(
      zoom(view, event.deltaY < 0 ? 1.25 : 0.8, local(event), smallest.current),
    );
  };

  const onPointerDown = (event: ReactPointerEvent) => {
    pointers.current.set(event.pointerId, local(event));
    box.current?.setPointerCapture?.(event.pointerId);
    drag.current = { start: local(event), moved: pointers.current.size > 1 };
  };

  const onPointerMove = (event: ReactPointerEvent) => {
    const before = pointers.current.get(event.pointerId);
    if (!before || !view || !drag.current) return;
    const now = local(event);
    if (pointers.current.size === 2) {
      const [a, b] = [...pointers.current.values()];
      const other = a === before ? b! : a!;
      const distance = (p: Point) =>
        Math.hypot(p[0] - other[0], p[1] - other[1]);
      const middle: Point = [(now[0] + other[0]) / 2, (now[1] + other[1]) / 2];
      if (distance(before) > 0)
        setView(
          zoom(
            view,
            distance(now) / distance(before),
            middle,
            smallest.current,
          ),
        );
      drag.current.moved = true;
    } else {
      const moved =
        Math.hypot(
          now[0] - drag.current.start[0],
          now[1] - drag.current.start[1],
        ) > CLICK_SLOP;
      drag.current.moved ||= moved;
      if (drag.current.moved)
        setView({
          ...view,
          x: view.x + now[0] - before[0],
          y: view.y + now[1] - before[1],
        });
    }
    pointers.current.set(event.pointerId, now);
  };

  const onPointerUp = (event: ReactPointerEvent) => {
    pointers.current.delete(event.pointerId);
    if (drag.current && !drag.current.moved && view && onPin)
      onPin(toWorld(world, view, local(event)));
    if (!pointers.current.size) drag.current = null;
  };

  const place = (point: Point) =>
    view
      ? {
          left: (point[0] - world.x) * view.scale + view.x,
          top: (point[1] - world.z) * view.scale + view.y,
        }
      : undefined;

  return (
    <div
      ref={box}
      className="world-map"
      data-pinning={onPin ? "true" : undefined}
      onWheel={onWheel}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerCancel={onPointerUp}
    >
      {view && (
        <img
          src={world.image}
          alt="Map of every island"
          draggable={false}
          style={{
            width: world.width * view.scale,
            height: world.height * view.scale,
            transform: `translate(${view.x}px, ${view.y}px)`,
          }}
        />
      )}
      {view && answer && (pin || opponent?.pin) && (
        <svg className="world-map-line" aria-hidden="true">
          {[pin, opponent?.pin].map(
            (point, index) =>
              point && (
                <line
                  key={index === 0 ? "you" : "opponent"}
                  x1={place(point)!.left}
                  y1={place(point)!.top}
                  x2={place(answer)!.left}
                  y2={place(answer)!.top}
                />
              ),
          )}
        </svg>
      )}
      {opponent?.pin && view && (
        <span
          className="world-pin world-opponent"
          style={place(opponent.pin)}
          title={`${opponent.name}'s guess`}
        />
      )}
      {pin && view && (
        <span className="world-pin" style={place(pin)} title="Your guess" />
      )}
      {answer && view && (
        <span
          className="world-pin world-answer"
          style={place(answer)}
          title="The real spot"
        />
      )}
    </div>
  );
}
