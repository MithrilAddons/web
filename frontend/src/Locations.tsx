import { useCallback, useEffect, useRef, useState } from "react";
import {
  LocationsError,
  getMe,
  getSolo,
  getWorld,
  sendGuess,
  sendNext,
  sendReady,
  startSolo,
  type Me,
  type Run,
  type World,
} from "./locationsApi";
import { Panorama } from "./Panorama";
import { WorldMap } from "./WorldMap";
import "./locations.css";

const BEST_KEY = "mithril.locations.best";
const MAX_RUN = 25_000;
// The server allows a guess one second late; ask for the result a little after that.
const SETTLE_MS = 1200;

function message(problem: unknown) {
  return problem instanceof LocationsError
    ? problem.message
    : "Something went wrong. Try again.";
}

function storedBest() {
  try {
    const value = Number(localStorage.getItem(BEST_KEY));
    return Number.isFinite(value) && value > 0 ? value : null;
  } catch {
    return null;
  }
}

/** A guest's best stays in this browser; returns it and whether this run beat it. */
function recordGuestBest(total: number) {
  const before = storedBest();
  if (before === null || total > before) {
    try {
      localStorage.setItem(BEST_KEY, String(total));
    } catch {
      // The best just isn't remembered.
    }
    return { best: total, beaten: before !== null };
  }
  return { best: before, beaten: false };
}

const points = (value: number) => value.toLocaleString("en-US");

/** The location game (working name): solo runs on the website for now. */
export function Locations() {
  const [world, setWorld] = useState<World | null>(null);
  const [me, setMe] = useState<Me | null>(null);
  const [run, setRun] = useState<Run | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(() => {
    getMe()
      .then(setMe)
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    getWorld()
      .then(setWorld)
      .catch((problem: unknown) => setError(message(problem)));
    refresh();
  }, [refresh]);

  const start = async () => {
    setBusy(true);
    setError("");
    try {
      setRun(await startSolo());
    } catch (problem) {
      setError(message(problem));
    } finally {
      setBusy(false);
    }
  };

  const leave = (reason = "") => {
    setRun(null);
    setError(reason);
    refresh();
  };

  return (
    <>
      <title>Locations · Mithril</title>
      {run && world ? (
        <SoloRun
          key={run.id}
          world={world}
          initial={run}
          onAgain={() => void start()}
          onLeave={leave}
        />
      ) : (
        <section className="locations-start">
          <div className="page-heading">
            <div>
              <h1>Locations</h1>
              <p className="quiet-label">
                Look around a spot in SkyBlock and find it on the map. Five
                rounds, 25 seconds each, up to 5,000 points a round.
              </p>
            </div>
          </div>
          <div className="curator-panel locations-panel">
            <h2>Solo</h2>
            <Best me={me} />
            <button
              type="button"
              className="primary"
              disabled={busy || !world}
              onClick={() => void start()}
            >
              Start a run
            </button>
            {me?.kind === "guest" && (
              <p className="quiet-label">
                Playing as a guest: your best stays in this browser.{" "}
                <a href="/link">Link your Minecraft account</a> to keep it.
              </p>
            )}
          </div>
          {error && <p role="alert">{error}</p>}
        </section>
      )}
    </>
  );
}

function Best({ me }: Readonly<{ me: Me | null }>) {
  if (me?.solo?.best) {
    return (
      <p className="quiet-label">
        Best {points(me.solo.best)} · Average {points(me.solo.average ?? 0)} ·{" "}
        {me.solo.runs} {me.solo.runs === 1 ? "run" : "runs"}
      </p>
    );
  }
  const local = me?.kind === "guest" ? storedBest() : null;
  return local ? (
    <p className="quiet-label">Best {points(local)}</p>
  ) : (
    <p className="quiet-label">No runs yet.</p>
  );
}

function SoloRun({
  world,
  initial,
  onAgain,
  onLeave,
}: Readonly<{
  world: World;
  initial: Run;
  onAgain: () => void;
  onLeave: (reason?: string) => void;
}>) {
  const [run, setRunState] = useState(initial);
  const [pin, setPin] = useState<[number, number] | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [mapOpen, setMapOpen] = useState(false);
  const offset = useRef(initial.now * 1000 - Date.now());
  // The revealed round keeps its panorama on screen to look at again.
  const shown = useRef(initial.panorama);
  shown.current = run.panorama ?? shown.current;

  const setRun = useCallback((next: Run) => {
    offset.current = next.now * 1000 - Date.now();
    setRunState(next);
  }, []);

  const act = useCallback(
    async (action: () => Promise<Run>) => {
      setBusy(true);
      setError("");
      try {
        setRun(await action());
      } catch (problem) {
        if (problem instanceof LocationsError && problem.status === 404)
          onLeave(problem.message);
        else setError(message(problem));
      } finally {
        setBusy(false);
      }
    },
    [setRun, onLeave],
  );

  const result = run.results[run.round - 1];
  const revealed = run.state === "revealed" || run.state === "finished";
  const answer: [number, number] | null = result
    ? [result.answer.x, result.answer.z]
    : null;

  useEffect(() => {
    if (revealed) setMapOpen(true);
  }, [revealed]);

  const next = () =>
    void act(async () => {
      const value = await sendNext(run.id, run.round);
      setPin(null);
      setMapOpen(false);
      return value;
    });

  return (
    <section className="solo-run" aria-label="Solo run">
      <div className="solo-bar">
        <span>
          Round {run.round} of {run.rounds}
        </span>
        <span>
          {points(run.total)} {run.total === 1 ? "point" : "points"}
        </span>
        {run.state === "playing" && run.deadline !== undefined && (
          <Countdown
            deadline={run.deadline}
            offset={offset}
            onExpired={() => void act(() => getSolo(run.id))}
          />
        )}
        <button
          type="button"
          className="secondary solo-map-toggle"
          onClick={() => setMapOpen((open) => !open)}
        >
          {mapOpen ? "Panorama" : "Map"}
        </button>
      </div>
      <div className="solo-stage" data-map={mapOpen ? "open" : undefined}>
        <div className="solo-view">
          {shown.current && (
            <Panorama
              src={shown.current}
              onReady={() => void act(() => sendReady(run.id, run.round))}
            />
          )}
          {run.state === "loading" && (
            <p className="solo-loading quiet-label">Loading the panorama…</p>
          )}
        </div>
        <aside className="solo-panel">
          <WorldMap
            world={world}
            pin={pin ?? (result?.pin as [number, number] | null) ?? null}
            answer={answer}
            onPin={run.state === "playing" ? setPin : undefined}
          />
          {run.state === "playing" && (
            <button
              type="button"
              className="primary"
              disabled={!pin || busy}
              onClick={() =>
                pin &&
                void act(() => sendGuess(run.id, run.round, pin[0], pin[1]))
              }
            >
              {pin ? "Guess" : "Click the map to place your pin"}
            </button>
          )}
          {result && <RoundResult world={world} result={result} />}
          {run.state === "revealed" && (
            <button
              type="button"
              className="primary"
              disabled={busy}
              onClick={next}
            >
              {run.round === run.rounds - 1 ? "Last round" : "Next round"}
            </button>
          )}
        </aside>
      </div>
      {error && <p role="alert">{error}</p>}
      {run.state === "finished" && (
        <Summary run={run} onAgain={onAgain} onLeave={() => onLeave()} />
      )}
    </section>
  );
}

function Countdown({
  deadline,
  offset,
  onExpired,
}: Readonly<{
  deadline: number;
  offset: { current: number };
  onExpired: () => void;
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
        expired.current();
      }
    }, 200);
    return () => clearInterval(timer);
  }, [deadline, offset]);
  const seconds = Math.max(0, Math.ceil(left / 1000));
  return (
    <span className="solo-clock" data-low={seconds <= 5 ? "true" : undefined}>
      {seconds > 0 ? `${seconds}s` : "Time’s up"}
    </span>
  );
}

function RoundResult({
  world,
  result,
}: Readonly<{ world: World; result: Run["results"][number] }>) {
  const guessed = world.islands.find((island) => island.key === result.guessed);
  let detail: string;
  if (!result.pin) detail = "No guess in time.";
  else if (result.distance === null)
    detail = `Wrong island: you picked ${guessed?.name ?? "the void"}.`;
  else detail = `${Math.round(result.distance)} blocks away.`;
  return (
    <div className="solo-result" aria-live="polite">
      <p className="solo-score">+{points(result.score)}</p>
      <p>{detail}</p>
      <p className="quiet-label">
        {result.answer.name}
        {result.captured_by ? ` · captured by ${result.captured_by}` : ""}
      </p>
    </div>
  );
}

function Summary({
  run,
  onAgain,
  onLeave,
}: Readonly<{ run: Run; onAgain: () => void; onLeave: () => void }>) {
  const [guest] = useState(() =>
    run.best ? null : recordGuestBest(run.total),
  );
  const best = run.best?.best ?? guest?.best ?? run.total;
  const beaten = run.best?.new_best ?? guest?.beaten ?? false;
  return (
    <div className="curator-panel solo-summary">
      <h2>
        {points(run.total)} of {points(MAX_RUN)}
      </h2>
      <ol className="solo-rounds">
        {run.results.map((result, index) => (
          <li key={index}>
            <span>{result.answer.name}</span>
            <span>{points(result.score)}</span>
          </li>
        ))}
      </ol>
      <p className="quiet-label">
        {beaten ? "New best! " : ""}Best {points(best)}
        {run.best?.average ? ` · Average ${points(run.best.average)}` : ""}
      </p>
      <div className="hero-actions">
        <button type="button" className="primary" onClick={onAgain}>
          Play again
        </button>
        <button type="button" className="secondary" onClick={onLeave}>
          Done
        </button>
      </div>
    </div>
  );
}
