import { useCallback, useEffect, useRef, useState } from "react";
import {
  LocationsError,
  acceptChallenge,
  createInvite,
  declineChallenge,
  duelGuess,
  duelReady,
  getDuel,
  getHistory,
  getInbox,
  joinInvite,
  leaveDuel,
  rematch,
  sendChallenge,
  type Duel,
  type Inbox,
  type Me,
  type PastDuel,
  type World,
} from "./locationsApi";
import { Countdown, guessDetail, message, points } from "./locationsShared";
import { Panorama } from "./Panorama";
import { WorldMap } from "./WorldMap";

const RETRY_MS = 2000;

/**
 * Keeps a held request going: asks again as soon as one returns, and after a short pause when
 * one fails. `load` gets the last revision it saw and returns the next value and its revision.
 */
function useHeld<T>(
  load: ((after: number, signal: AbortSignal) => Promise<T>) | null,
  revision: (value: T) => number,
  onValue: (value: T) => void,
  onFail?: (problem: unknown) => boolean,
) {
  const latest = useRef({ revision, onValue, onFail });
  latest.current = { revision, onValue, onFail };
  useEffect(() => {
    if (!load) return;
    const controller = new AbortController();
    let after = -1;
    const ask = async (): Promise<void> => {
      if (controller.signal.aborted) return;
      try {
        const value = await load(after, controller.signal);
        if (controller.signal.aborted) return;
        after = latest.current.revision(value);
        latest.current.onValue(value);
      } catch (error_) {
        if (controller.signal.aborted || latest.current.onFail?.(error_))
          return;
        await new Promise((resolve) => setTimeout(resolve, RETRY_MS));
      }
      return ask();
    };
    void ask();
    return () => controller.abort();
  }, [load]);
}

function inviteLink(code: string) {
  return `${window.location.origin}/games/locations?join=${code}`;
}

function readJoinCode() {
  const code = new URLSearchParams(window.location.search).get("join");
  return code && /^[A-Za-z0-9]{6}$/.test(code) ? code.toUpperCase() : null;
}

/** Duels: find an opponent, then play; the inbox keeps you reachable while the page is open. */
export function Duels({
  world,
  me,
  onChanged,
}: Readonly<{ world: World | null; me: Me | null; onChanged: () => void }>) {
  const [inbox, setInbox] = useState<Inbox | null>(null);
  const [duelId, setDuelId] = useState<string | null>(null);
  const [joinCode, setJoinCode] = useState(readJoinCode);

  useHeld(
    getInbox,
    (value) => value.revision,
    (value) => {
      setInbox(value);
      if (value.duel) setDuelId(value.duel);
    },
  );

  const done = () => {
    setDuelId(null);
    onChanged();
  };

  if (duelId && world)
    return <DuelMatch key={duelId} id={duelId} world={world} onDone={done} />;
  return (
    <Lobby
      inbox={inbox}
      me={me}
      joinCode={joinCode}
      onJoined={(id) => {
        setJoinCode(null);
        window.history.replaceState(null, "", "/games/locations");
        setDuelId(id);
      }}
    />
  );
}

function Lobby({
  inbox,
  me,
  joinCode,
  onJoined,
}: Readonly<{
  inbox: Inbox | null;
  me: Me | null;
  joinCode: string | null;
  onJoined: (id: string) => void;
}>) {
  const [name, setName] = useState("");
  const [invite, setInvite] = useState<{
    code: string;
    expires: number;
  } | null>(null);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const act = async (action: () => Promise<unknown>) => {
    setBusy(true);
    setError("");
    try {
      await action();
    } catch (error_) {
      setError(message(error_));
    } finally {
      setBusy(false);
    }
  };

  const challenge = (event: { preventDefault: () => void }) => {
    event.preventDefault();
    if (name.trim())
      void act(async () => {
        await sendChallenge(name.trim());
        setName("");
      });
  };

  const outgoing = inbox?.outgoing.find((item) => item.kind === "challenge");
  return (
    <section className="duel-lobby">
      {joinCode && (
        <div className="curator-panel locations-panel duel-join">
          <h2>Join a duel</h2>
          <p>Someone sent you an invite link.</p>
          <button
            type="button"
            className="primary"
            disabled={busy}
            onClick={() =>
              void act(async () => onJoined((await joinInvite(joinCode)).duel))
            }
          >
            Join duel {joinCode}
          </button>
        </div>
      )}
      {inbox?.incoming.map((item) => (
        <div key={item.id} className="curator-panel duel-incoming">
          <p>
            <strong>{item.from}</strong> challenged you to a duel.
          </p>
          <div className="hero-actions">
            <button
              type="button"
              className="primary"
              disabled={busy}
              onClick={() =>
                void act(async () =>
                  onJoined((await acceptChallenge(item.id)).duel),
                )
              }
            >
              Accept
            </button>
            <button
              type="button"
              className="secondary"
              disabled={busy}
              onClick={() => void act(() => declineChallenge(item.id))}
            >
              Decline
            </button>
          </div>
        </div>
      ))}
      <div className="duel-ways">
        <form className="curator-panel locations-panel" onSubmit={challenge}>
          <h2>Challenge a player</h2>
          <p className="quiet-label">
            They need this page open. Challenges last two minutes.
          </p>
          <label className="duel-name">
            Minecraft name{" "}
            <input
              value={name}
              maxLength={16}
              autoComplete="off"
              onChange={(event) => setName(event.target.value)}
            />
          </label>
          {outgoing ? (
            <p className="quiet-label">
              Waiting for {outgoing.to} to accept…{" "}
              <button
                type="button"
                className="secondary"
                onClick={() => void act(() => declineChallenge(outgoing.id))}
              >
                Cancel
              </button>
            </p>
          ) : (
            <button
              type="submit"
              className="primary"
              disabled={busy || !name.trim()}
            >
              Challenge
            </button>
          )}
        </form>
        <div className="curator-panel locations-panel">
          <h2>Invite a friend</h2>
          <p className="quiet-label">
            A link anyone can open to duel you, even without an account. It
            works once, for ten minutes.
          </p>
          {invite ? (
            <div className="duel-invite">
              <code>{inviteLink(invite.code)}</code>
              <button
                type="button"
                className="secondary"
                onClick={() =>
                  void navigator.clipboard
                    ?.writeText(inviteLink(invite.code))
                    .then(() => setCopied(true))
                }
              >
                {copied ? "Copied" : "Copy link"}
              </button>
            </div>
          ) : (
            <button
              type="button"
              className="primary"
              disabled={busy}
              onClick={() =>
                void act(async () => {
                  setInvite(await createInvite());
                  setCopied(false);
                })
              }
            >
              Create invite link
            </button>
          )}
        </div>
      </div>
      {error && <p role="alert">{error}</p>}
      <Rating me={me} />
    </section>
  );
}

function Rating({ me }: Readonly<{ me: Me | null }>) {
  const [history, setHistory] = useState<PastDuel[] | null>(null);
  const linked = me?.kind === "linked";
  useEffect(() => {
    if (!linked) return;
    getHistory()
      .then((value) => setHistory(value.duels))
      .catch(() => setHistory([]));
  }, [linked]);
  if (!me) return null;
  if (!linked)
    return (
      <p className="quiet-label">
        Playing as {me.name ?? "a guest"}: duels with guests are unrated.{" "}
        <a href="/link">Link your Minecraft account</a> to get a rating.
      </p>
    );
  const rating = me.rating;
  return (
    <div className="curator-panel locations-panel">
      <h2>Your rating</h2>
      {rating ? (
        <p>
          {rating.rating}
          {rating.provisional ? "?" : ""} · {rating.wins} won · {rating.losses}{" "}
          lost · {rating.draws} drawn
          {rating.provisional && (
            <span className="quiet-label">
              {" "}
              · provisional until a few more duels
            </span>
          )}
        </p>
      ) : (
        <p className="quiet-label">
          Everyone starts at 1500. Your first duels settle it.
        </p>
      )}
      {history && history.length > 0 && (
        <ol className="duel-history">
          {history.map((duel) => (
            <li key={duel.id}>
              <span>
                {PAST[duel.result]} against {duel.opponent}
              </span>
              <span className="quiet-label">
                {duel.rating
                  ? signed(duel.rating.after - duel.rating.before)
                  : "unrated"}
              </span>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

const signed = (value: number) => (value >= 0 ? `+${value}` : `${value}`);
const PAST: Record<PastDuel["result"], string> = {
  win: "Won",
  loss: "Lost",
  draw: "Drew",
};
const HEADINGS: Record<NonNullable<Duel["finished"]>["result"], string> = {
  win: "You won!",
  loss: "You lost",
  draw: "A draw",
};

function damage(result: Duel["results"][number], opponent: string) {
  if (result.lost === null) return "Even round: no damage.";
  return result.lost
    ? `You lose ${points(result.damage)} health.`
    : `${opponent} loses ${points(result.damage)} health.`;
}

function status(duel: Duel) {
  const opponent = duel.opponent.name;
  if (duel.state === "loading")
    return duel.countdown
      ? "Get ready…"
      : "Waiting for both panoramas to load…";
  if (duel.state !== "playing") return "";
  if (duel.me.guessed) return `Waiting for ${opponent}…`;
  return duel.opponent.guessed ? `${opponent} has guessed!` : "";
}

function opponentNote(opponent: Duel["opponent"]) {
  if (!opponent.connected) return "reconnecting…";
  return opponent.guest ? "guest" : undefined;
}

function HealthBar({
  name,
  health,
  total,
  note,
}: Readonly<{ name: string; health: number; total: number; note?: string }>) {
  return (
    <div className="duel-health">
      <span>
        {name}
        {note && <span className="quiet-label"> · {note}</span>}
      </span>
      <meter
        min={0}
        max={total}
        value={health}
        aria-label={`${name}'s health`}
      />
      <span className="duel-health-value">{points(health)}</span>
    </div>
  );
}

const REASONS: Record<string, (opponent: string, won: boolean) => string> = {
  health: (opponent, won) =>
    won ? `${opponent} ran out of health.` : "You ran out of health.",
  rounds: () => "Every round was played.",
  forfeit: (opponent, won) =>
    won ? `${opponent} left the duel.` : "You left the duel.",
  cancelled: () => "Both players left, so the duel was cancelled.",
};

function DuelMatch({
  id,
  world,
  onDone,
}: Readonly<{ id: string; world: World; onDone: () => void }>) {
  const [duel, setDuel] = useState<Duel | null>(null);
  const [pin, setPin] = useState<[number, number] | null>(null);
  const [error, setError] = useState("");
  const [mapOpen, setMapOpen] = useState(false);
  const [rematchSent, setRematchSent] = useState(false);
  const offset = useRef(0);
  const shown = useRef<string | undefined>(undefined);
  const round = useRef(0);

  const update = useCallback((next: Duel) => {
    offset.current = next.now * 1000 - Date.now();
    if (next.round !== round.current) {
      round.current = next.round;
      setPin(null);
      setMapOpen(false);
    }
    setDuel((current) =>
      current && current.version > next.version ? current : next,
    );
  }, []);

  const load = useCallback(
    (after: number, signal: AbortSignal) => getDuel(id, after, signal),
    [id],
  );
  useHeld(
    load,
    (value) => value.version,
    update,
    (problem) => {
      if (problem instanceof LocationsError && problem.status === 404) {
        onDone();
        return true;
      }
      return false;
    },
  );

  const act = async (action: () => Promise<unknown>) => {
    setError("");
    try {
      const value = await action();
      if (value && typeof value === "object" && "state" in value)
        update(value as Duel);
    } catch (error_) {
      setError(message(error_));
    }
  };

  useEffect(() => {
    if (duel?.state === "revealed" || duel?.state === "finished")
      setMapOpen(true);
  }, [duel?.state]);

  if (!duel) return <p className="quiet-label">Loading the duel…</p>;
  shown.current = duel.panorama ?? shown.current;
  const result = duel.results.find((item) => item.round === duel.round);
  const opponent = duel.opponent;

  return (
    <section className="solo-run duel-match" aria-label="Duel">
      <div className="duel-bar">
        <HealthBar
          name={duel.me.name}
          health={duel.me.health}
          total={duel.health}
        />
        <div className="duel-middle">
          <span>
            Round {duel.round} of {duel.rounds}
            {duel.multiplier > 1 && (
              <span className="duel-multiplier">
                {" "}
                · damage ×{duel.multiplier}
              </span>
            )}
          </span>
          <DuelClock duel={duel} offset={offset} />
        </div>
        <HealthBar
          name={opponent.name}
          health={opponent.health}
          total={duel.health}
          note={opponentNote(opponent)}
        />
      </div>
      {status(duel) && (
        <p className="quiet-label duel-status">{status(duel)}</p>
      )}
      <div className="solo-stage" data-map={mapOpen ? "open" : undefined}>
        <div className="solo-view">
          {shown.current && (
            <Panorama
              src={shown.current}
              onReady={() => void act(() => duelReady(id, duel.round))}
            />
          )}
        </div>
        <aside className="solo-panel">
          <WorldMap
            world={world}
            pin={pin ?? result?.me.pin ?? null}
            answer={result ? [result.answer.x, result.answer.z] : null}
            opponent={
              result ? { pin: result.opponent.pin, name: opponent.name } : null
            }
            onPin={
              duel.state === "playing" && !duel.me.guessed ? setPin : undefined
            }
          />
          {duel.state === "playing" && !duel.me.guessed && (
            <button
              type="button"
              className="primary"
              disabled={!pin}
              onClick={() =>
                pin && void act(() => duelGuess(id, duel.round, pin[0], pin[1]))
              }
            >
              {pin ? "Guess" : "Click the map to place your pin"}
            </button>
          )}
          {result && (
            <DuelResult
              world={world}
              result={result}
              opponent={opponent.name}
            />
          )}
        </aside>
      </div>
      <button
        type="button"
        className="secondary solo-map-toggle"
        onClick={() => setMapOpen((open) => !open)}
      >
        {mapOpen ? "Panorama" : "Map"}
      </button>
      {error && <p role="alert">{error}</p>}
      {duel.finished ? (
        <DuelEnd
          finished={duel.finished}
          opponent={opponent.name}
          rematchSent={rematchSent}
          onRematch={() =>
            void act(async () => {
              await rematch(id);
              setRematchSent(true);
            })
          }
          onDone={onDone}
        />
      ) : (
        <button
          type="button"
          className="secondary duel-leave"
          onClick={() => void act(() => leaveDuel(id))}
        >
          Forfeit
        </button>
      )}
    </section>
  );
}

function DuelClock({
  duel,
  offset,
}: Readonly<{ duel: Duel; offset: { current: number } }>) {
  if (duel.state === "playing" && duel.deadline !== undefined)
    return <Countdown deadline={duel.deadline} offset={offset} />;
  if (duel.state === "loading" && duel.countdown !== undefined)
    return (
      <Countdown
        deadline={duel.countdown}
        offset={offset}
        label={(seconds) => (seconds > 0 ? `Starting in ${seconds}` : "Go!")}
      />
    );
  if (duel.state === "revealed" && duel.next !== undefined)
    return (
      <Countdown
        deadline={duel.next}
        offset={offset}
        label={(seconds) => `Next round in ${seconds}`}
      />
    );
  return null;
}

function DuelResult({
  world,
  result,
  opponent,
}: Readonly<{
  world: World;
  result: Duel["results"][number];
  opponent: string;
}>) {
  return (
    <div className="solo-result" aria-live="polite">
      <p className="solo-score">
        +{points(result.me.score)}{" "}
        <span className="quiet-label">
          vs {opponent} +{points(result.opponent.score)}
        </span>
      </p>
      <p>{guessDetail(world, result.me)}</p>
      <p>{damage(result, opponent)}</p>
      <p className="quiet-label">
        {result.answer.name}
        {result.captured_by ? ` · captured by ${result.captured_by}` : ""}
      </p>
    </div>
  );
}

function DuelEnd({
  finished,
  opponent,
  rematchSent,
  onRematch,
  onDone,
}: Readonly<{
  finished: NonNullable<Duel["finished"]>;
  opponent: string;
  rematchSent: boolean;
  onRematch: () => void;
  onDone: () => void;
}>) {
  const rating = finished.rating;
  return (
    <div className="curator-panel solo-summary">
      <h2>{HEADINGS[finished.result]}</h2>
      <p>{REASONS[finished.reason]?.(opponent, finished.result === "win")}</p>
      {rating && (
        <p>
          Rating {rating.before} → {rating.after}
          {rating.provisional ? "?" : ""} (
          {signed(rating.after - rating.before)})
        </p>
      )}
      {!rating && finished.reason !== "cancelled" && (
        <p className="quiet-label">This duel was unrated.</p>
      )}
      <div className="hero-actions">
        <button
          type="button"
          className="primary"
          disabled={rematchSent}
          onClick={onRematch}
        >
          {rematchSent ? `Waiting for ${opponent}…` : "Rematch"}
        </button>
        <button type="button" className="secondary" onClick={onDone}>
          Back to duels
        </button>
      </div>
    </div>
  );
}
