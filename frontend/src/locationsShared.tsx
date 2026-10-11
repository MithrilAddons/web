import { useEffect, useRef, useState } from "react";
import { LocationsError, type World } from "./locationsApi";

// The server allows a guess one second late; ask for the result a little after that.
const SETTLE_MS = 1200;

export const points = (value: number) => value.toLocaleString("en-US");

export function message(problem: unknown) {
  return problem instanceof LocationsError
    ? problem.message
    : "Something went wrong. Try again.";
}

/** What became of one guess: how far off, the wrong island, or none at all. */
export function guessDetail(
  world: World,
  guess: {
    pin: [number, number] | null;
    distance: number | null;
    guessed: string | null;
  },
  who = "you",
) {
  if (!guess.pin) return "No guess in time.";
  if (guess.distance === null) {
    const island = world.islands.find((item) => item.key === guess.guessed);
    return `Wrong island: ${who} picked ${island?.name ?? "the void"}.`;
  }
  return `${Math.round(guess.distance)} blocks away.`;
}

/** Seconds left until a server deadline; `offset` is the server clock minus this one. */
export function Countdown({
  deadline,
  offset,
  onExpired,
  label = (seconds: number) => (seconds > 0 ? `${seconds}s` : "Time’s up"),
}: Readonly<{
  deadline: number;
  offset: { current: number };
  onExpired?: () => void;
  label?: (seconds: number) => string;
}>) {
  const remaining = () => deadline * 1000 - (Date.now() + offset.current);
  const [left, setLeft] = useState(remaining);
  const expired = useRef(onExpired);
  expired.current = onExpired;
  useEffect(() => {
    let done = false;
    const timer = setInterval(() => {
      const value = deadline * 1000 - (Date.now() + offset.current);
      setLeft(value);
      if (!done && value < -SETTLE_MS) {
        done = true;
        expired.current?.();
      }
    }, 200);
    return () => clearInterval(timer);
  }, [deadline, offset]);
  const seconds = Math.max(0, Math.ceil(left / 1000));
  return (
    <span className="solo-clock" data-low={seconds <= 5 ? "true" : undefined}>
      {label(seconds)}
    </span>
  );
}
