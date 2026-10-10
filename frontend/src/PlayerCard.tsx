import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import {
  formatTime,
  getPlayerCard,
  type PlayerCardData,
} from "./playerCardApi";

export function PartyPlayerName({
  user,
}: Readonly<{
  user: { uuid: string; name: string };
}>) {
  const [open, setOpen] = useState(false);
  const button = useRef<HTMLButtonElement>(null);
  return (
    <>
      <button
        ref={button}
        className="party-player-name"
        aria-haspopup="dialog"
        onClick={() => setOpen(true)}
      >
        {user.name}
      </button>
      {open && (
        <PlayerCard
          user={user}
          partyMember
          onClose={() => {
            setOpen(false);
            button.current?.focus();
          }}
        />
      )}
    </>
  );
}

export function PlayerCard({
  user,
  onClose,
  partyMember = false,
}: {
  user: { uuid: string; name: string };
  onClose: () => void;
  partyMember?: boolean;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const close = () => {
    dialog.current?.close();
    onClose();
  };
  useEffect(() => {
    const element = dialog.current!;
    element.showModal();
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      element.close();
      document.body.style.overflow = previous;
    };
  }, []);
  return createPortal(
    <dialog
      ref={dialog}
      className="player-card"
      aria-labelledby="player-card-title"
      onCancel={(event) => {
        event.preventDefault();
        close();
      }}
      onClick={(event) => {
        if (event.target !== event.currentTarget) return;
        const box = event.currentTarget.getBoundingClientRect();
        if (
          event.clientX < box.left ||
          event.clientX > box.right ||
          event.clientY < box.top ||
          event.clientY > box.bottom
        )
          close();
      }}
    >
      <header className="player-card-heading">
        <div>
          <p className="quiet-label">Player card</p>
          <h2 id="player-card-title">{user.name}</h2>
        </div>
        <button
          className="card-close"
          onClick={close}
          aria-label="Close player card"
        >
          ×
        </button>
      </header>
      <PlayerStats user={user} partyMember={partyMember} />
    </dialog>,
    document.body,
  );
}

export function PlayerStats({
  user,
  partyMember = false,
}: Readonly<{
  user: { uuid: string; name: string };
  partyMember?: boolean;
}>) {
  const [data, setData] = useState<PlayerCardData | null>(null);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const [mode, setMode] = useState("M7");
  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    const deadline = setTimeout(() => controller.abort(), 10000);
    void getPlayerCard(user.uuid, controller.signal, partyMember)
      .then(
        (value) => {
          if (active) setData(value);
        },
        (reason: unknown) => {
          if (active)
            setError(
              reason instanceof Error &&
                reason.message.startsWith("Your session")
                ? reason.message
                : "Player stats are unavailable. Try again shortly.",
            );
        },
      )
      .finally(() => clearTimeout(deadline));
    return () => {
      active = false;
      controller.abort();
      clearTimeout(deadline);
    };
  }, [user.uuid, attempt, partyMember]);
  const record = data?.floors.find((row) => row.floor === mode);
  const count = (value: number | null) =>
    value === null ? "—" : value.toLocaleString();
  return (
    <>
      {data?.profile && <p className="quiet-label">{data.profile.name}</p>}
      {!data && !error && (
        <output className="card-status">Loading stats…</output>
      )}
      {error && (
        <div className="card-status">
          <p role="alert">{error}</p>
          <button
            onClick={() => {
              setError("");
              setAttempt(attempt + 1);
            }}
          >
            Try again
          </button>
        </div>
      )}
      {data && (
        <>
          {!data.profile && (
            <p className="card-status">No SkyBlock profile found.</p>
          )}
          <dl className="card-stats">
            <div>
              <dt>Catacombs</dt>
              <dd>
                {data.catacombs === null
                  ? "—"
                  : data.catacombs.level.toFixed(2)}
              </dd>
            </div>
            <div>
              <dt>Secrets</dt>
              <dd>{count(data.secrets)}</dd>
            </div>
            <div>
              <dt>Magical Power</dt>
              <dd>{count(data.magical_power)}</dd>
              <span className="quiet-label">Highest recorded</span>
            </div>
          </dl>
          <section className="card-section" aria-labelledby="card-pbs">
            <h3 id="card-pbs">S+ personal bests</h3>
            <table className="card-pbs">
              <thead>
                <tr>
                  <th scope="col">Floor</th>
                  <th scope="col">Normal</th>
                  <th scope="col">Master</th>
                </tr>
              </thead>
              <tbody>
                {Array.from({ length: 7 }, (_, index) => index + 1).map(
                  (floor) => (
                    <tr key={floor}>
                      <th scope="row">{floor}</th>
                      {["F", "M"].map((prefix) => (
                        <td key={prefix}>
                          {formatTime(
                            data.floors.find(
                              (row) => row.floor === `${prefix}${floor}`,
                            )?.s_plus_ms,
                          )}
                        </td>
                      ))}
                    </tr>
                  ),
                )}
              </tbody>
            </table>
          </section>
          <section className="card-section" aria-labelledby="card-mod-records">
            <div className="card-section-heading">
              <h3 id="card-mod-records">Mod records</h3>
              <div className="card-modes" aria-label="Record floor">
                {["F7", "M7"].map((floor) => (
                  <button
                    key={floor}
                    aria-pressed={mode === floor}
                    onClick={() => setMode(floor)}
                  >
                    {floor}
                  </button>
                ))}
              </div>
            </div>
            <p className="quiet-label">Account-wide · Real time</p>
            <dl className="card-stats mod-stats">
              {[
                ["Solo clear PB", record?.solo_clear_ms],
                ["SS time", record?.ss_ms],
                ["Terminal phase PB", record?.terminals_ms],
              ].map(([label, value]) => (
                <div key={label}>
                  <dt>{label}</dt>
                  <dd>
                    {formatTime(typeof value === "number" ? value : null)}
                  </dd>
                </div>
              ))}
            </dl>
            {!data.mod_records_available && (
              <p className="quiet-label">No mod data synced yet.</p>
            )}
          </section>
          <footer className="card-footer">
            <span>Hypixel · Selected profile</span>
            <span>
              Updated{" "}
              {new Date(data.fetched_at * 1000).toLocaleTimeString([], {
                hour: "2-digit",
                minute: "2-digit",
              })}
            </span>
          </footer>
        </>
      )}
    </>
  );
}
