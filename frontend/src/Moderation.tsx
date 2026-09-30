import { useEffect, useRef, useState } from "react";
import "./moderation.css";

type Access = {
  role: "owner" | "moderator";
  moderators: string[];
  network_bans_available: boolean;
};
type RecordRow = {
  id: string;
  floor: string;
  kind: string;
  real_ms: number;
  ticks: number;
  source: string;
  status: string;
};
type Case = {
  id: string;
  kind: string;
  expires: number | null;
  revoked: number | null;
  appeal_open: number;
  reason: string;
};
type Player = {
  uuid: string;
  name?: string;
  records: RecordRow[];
  cases: Case[];
};
type Audit = {
  id: number;
  at: number;
  actor: string;
  action: string;
  subject: string;
  reason: string;
  before_json: string;
  after_json: string;
};

async function request<T>(path: string, body?: object): Promise<T> {
  const response = await fetch(`/api/v1/moderation/${path}`, {
    method: body ? "POST" : "GET",
    credentials: "same-origin",
    cache: "no-store",
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify({ version: 1, ...body }) : undefined,
    signal: AbortSignal.timeout(15000),
  });
  if (!response.ok) {
    const value = (await response.json()) as { detail?: unknown };
    throw new Error(
      typeof value.detail === "string"
        ? value.detail
        : "Check the entered values and try again.",
    );
  }
  return response.json() as Promise<T>;
}

function timestamp(value: number | null) {
  return value === null ? "Permanent" : new Date(value * 1000).toLocaleString();
}

export function Moderation() {
  const [access, setAccess] = useState<Access | null>(null);
  const [query, setQuery] = useState("");
  const [player, setPlayer] = useState<Player | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const working = useRef(false);
  const [audit, setAudit] = useState<Audit[]>([]);
  const [reason, setReason] = useState("");
  const [kind, setKind] = useState("ban");
  const [duration, setDuration] = useState("7");
  const [selected, setSelected] = useState<string[]>([]);
  const [reports, setReports] = useState<string[]>([]);
  const [evidence, setEvidence] = useState<unknown>(null);
  useEffect(() => {
    let active = true;
    void request<Access>("access").then(
      (value) => {
        if (active) setAccess(value);
      },
      (err: Error) => {
        if (active) setError(err.message);
      },
    );
    return () => {
      active = false;
    };
  }, []);

  async function perform(action: () => Promise<void>) {
    if (working.current) return;
    working.current = true;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await action();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Request failed");
    } finally {
      working.current = false;
      setBusy(false);
    }
  }

  async function findPlayer() {
    setPlayer(null);
    setReports([]);
    setSelected([]);
    setEvidence(null);
    setReason("");
    const value = query.trim().replaceAll("-", "");
    const identity = /^[0-9a-f]{32}$/i.test(value)
      ? { uuid: value.toLowerCase(), name: undefined }
      : await request<{ uuid: string; name: string }>(
          `resolve/${encodeURIComponent(query.trim())}`,
        );
    const data = await request<Player>(`player/${identity.uuid}`);
    setPlayer({ ...data, name: identity.name });
  }

  async function mutate(path: string, body: object) {
    if (!reason.trim()) throw new Error("Enter a reason.");
    await request(path, { ...body, reason: reason.trim() });
    setNotice("Saved.");
    setReason("");
    setSelected([]);
    setEvidence(null);
    if (player)
      setPlayer({
        ...(await request<Player>(`player/${player.uuid}`)),
        name: player.name,
      });
    setAccess(await request<Access>("access"));
    setAudit((await request<{ entries: Audit[] }>("audit")).entries);
  }

  return (
    <section className="moderation" aria-labelledby="moderation-title">
      <header>
        <h1 id="moderation-title">Moderation</h1>
        {access && <span className="quiet-label">{access.role}</span>}
      </header>
      {error && <p role="alert">{error}</p>}
      {notice && <output>{notice}</output>}
      {!access && !error && <output>Checking access…</output>}
      {access && (
        <>
          <form
            className="moderation-search"
            onSubmit={(event) => {
              event.preventDefault();
              void perform(findPlayer);
            }}
          >
            <label>
              Player{" "}
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Minecraft username or UUID"
                required
                maxLength={36}
              />
            </label>
            <button type="submit" disabled={busy}>
              Find player
            </button>
          </form>
          {player && (
            <>
              <h2>{player.name ?? "Player"}</h2>
              <code>{player.uuid}</code>
              <label>
                Reason{" "}
                <textarea
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                  maxLength={500}
                  rows={2}
                />
              </label>
              <h3>Records</h3>
              {!player.records.length && <p>No records.</p>}
              <ul className="moderation-records">
                {player.records.map((record) => (
                  <li key={record.id}>
                    <label className="moderation-check">
                      <input
                        type="checkbox"
                        checked={selected.includes(record.id)}
                        onChange={(e) =>
                          setSelected(
                            e.target.checked
                              ? [...selected, record.id]
                              : selected.filter((id) => id !== record.id),
                          )
                        }
                      />
                      {record.floor}{" "}
                      {record.kind === "solo_clear" ? "Soloclear" : "Terminals"}{" "}
                      · {(record.real_ms / 1000).toFixed(3)}s · {record.ticks}{" "}
                      ticks
                    </label>
                    <span className="quiet-label">
                      {record.status} · {record.source.replaceAll("_", " ")}
                    </span>
                    <div className="moderation-actions">
                      <button
                        type="button"
                        className="secondary"
                        disabled={busy}
                        onClick={() =>
                          void perform(async () =>
                            setEvidence(await request(`evidence/${record.id}`)),
                          )
                        }
                      >
                        Evidence
                      </button>
                      <button
                        type="button"
                        className="secondary"
                        disabled={busy || !reason.trim()}
                        onClick={() =>
                          void perform(() =>
                            mutate("record", {
                              record_id: record.id,
                              expected_status: record.status,
                              action:
                                record.status === "eligible"
                                  ? "invalidate"
                                  : "restore",
                            }),
                          )
                        }
                      >
                        {record.status === "eligible"
                          ? "Invalidate"
                          : "Restore"}
                      </button>
                    </div>
                    {record.status === "eligible" && (
                      <Correction
                        record={record}
                        disabled={busy || !reason.trim()}
                        onSave={(values) =>
                          perform(() =>
                            mutate("record", {
                              record_id: record.id,
                              expected_status: record.status,
                              action: "correct",
                              ...values,
                            }),
                          )
                        }
                      />
                    )}
                  </li>
                ))}
              </ul>
              {evidence !== null && (
                <details open>
                  <summary>Record evidence</summary>
                  <pre>{JSON.stringify(evidence, null, 2)}</pre>
                </details>
              )}
              <form
                className="moderation-sanction"
                onSubmit={(event) => {
                  event.preventDefault();
                  void perform(() =>
                    mutate("sanction", {
                      uuid: player.uuid,
                      kind,
                      expires:
                        duration === "permanent"
                          ? null
                          : Math.floor(Date.now() / 1000) +
                            Number(duration) * 86400,
                      record_ids: selected,
                      report_ids: reports,
                    }),
                  );
                }}
              >
                <h3>Restriction</h3>
                <label>
                  Action{" "}
                  <select
                    value={kind}
                    onChange={(e) => setKind(e.target.value)}
                  >
                    <option value="ban">Account ban</option>
                    <option value="mute">Chat mute</option>
                    {access.network_bans_available && (
                      <option value="network_ban">Account and IP ban</option>
                    )}
                  </select>
                </label>
                <label>
                  Duration{" "}
                  <select
                    value={duration}
                    onChange={(e) => setDuration(e.target.value)}
                  >
                    <option value="1">1 day</option>
                    <option value="7">7 days</option>
                    <option value="30">30 days</option>
                    <option value="permanent">Permanent</option>
                  </select>
                </label>
                {kind === "network_ban" && (
                  <p>Also blocks other accounts using the same IP address.</p>
                )}
                <p className="quiet-label">
                  Selected records provide evidence for this case.
                </p>
                <button type="submit" disabled={busy || !reason.trim()}>
                  Apply restriction
                </button>
              </form>
              <h3>Cases</h3>
              {!player.cases.length && <p>No cases.</p>}
              <ul className="moderation-records">
                {player.cases.map((item) => (
                  <li key={item.id}>
                    <strong>{item.kind.replaceAll("_", " ")}</strong> ·{" "}
                    {item.revoked ? "Revoked" : timestamp(item.expires)}
                    <p>{item.reason}</p>
                    <div className="moderation-actions">
                      <button
                        type="button"
                        className="secondary"
                        disabled={busy}
                        onClick={() =>
                          void perform(async () =>
                            setEvidence(
                              await request(`case/${item.id}/evidence`),
                            ),
                          )
                        }
                      >
                        Case evidence
                      </button>
                      {!item.revoked && (
                        <button
                          type="button"
                          className="secondary"
                          disabled={busy || !reason.trim()}
                          onClick={() =>
                            void perform(() =>
                              mutate("case", {
                                case_id: item.id,
                                action: "revoke",
                              }),
                            )
                          }
                        >
                          Revoke
                        </button>
                      )}
                      <button
                        type="button"
                        className="secondary"
                        disabled={busy || !reason.trim()}
                        onClick={() =>
                          void perform(() =>
                            mutate("case", {
                              case_id: item.id,
                              action: item.appeal_open
                                ? "close_appeal"
                                : "open_appeal",
                            }),
                          )
                        }
                      >
                        {item.appeal_open ? "Close appeal" : "Open appeal"}
                      </button>
                    </div>
                  </li>
                ))}
              </ul>
              {access.role === "owner" && (
                <section>
                  <h3>Moderator access</h3>
                  <button
                    type="button"
                    className="secondary"
                    disabled={busy || !reason.trim()}
                    onClick={() =>
                      void perform(() =>
                        mutate("access", {
                          uuid: player.uuid,
                          enabled: !access.moderators.includes(player.uuid),
                        }),
                      )
                    }
                  >
                    {access.moderators.includes(player.uuid)
                      ? "Revoke moderator"
                      : "Grant moderator"}
                  </button>
                </section>
              )}
            </>
          )}
          <ChatReview
            disabled={busy}
            onSelect={async (uuid, reportId) => {
              await perform(async () => {
                setPlayer(await request<Player>(`player/${uuid}`));
                setQuery(uuid);
                setReports([reportId]);
                setSelected([]);
                setReason("");
                setEvidence(null);
              });
            }}
          />
          <section>
            <h2>Audit log</h2>
            <button
              type="button"
              className="secondary"
              disabled={busy}
              onClick={() =>
                void perform(async () =>
                  setAudit(
                    (await request<{ entries: Audit[] }>("audit")).entries,
                  ),
                )
              }
            >
              Refresh audit
            </button>
            <ol className="moderation-records">
              {audit.map((entry) => (
                <li key={entry.id}>
                  <strong>{entry.action.replaceAll("_", " ")}</strong> ·{" "}
                  {timestamp(entry.at)}
                  <p>{entry.reason}</p>
                  <p>
                    Moderator: <code>{entry.actor}</code>
                  </p>
                  <p>
                    Player: <code>{entry.subject}</code>
                  </p>
                  <details>
                    <summary>Changes</summary>
                    <pre>
                      {JSON.stringify(
                        {
                          before: JSON.parse(entry.before_json) as unknown,
                          after: JSON.parse(entry.after_json) as unknown,
                        },
                        null,
                        2,
                      )}
                    </pre>
                  </details>
                </li>
              ))}
            </ol>
            {audit.length > 0 && (
              <button
                type="button"
                className="secondary"
                disabled={busy}
                onClick={() =>
                  void perform(async () => {
                    const older = await request<{ entries: Audit[] }>(
                      `audit?before=${audit.at(-1)!.id}`,
                    );
                    setAudit([...audit, ...older.entries]);
                    if (!older.entries.length) setNotice("No older actions.");
                  })
                }
              >
                Older actions
              </button>
            )}
          </section>
        </>
      )}
    </section>
  );
}

function Correction({
  record,
  disabled,
  onSave,
}: Readonly<{
  record: RecordRow;
  disabled: boolean;
  onSave: (value: { real_ms: number; ticks: number }) => Promise<void>;
}>) {
  const [milliseconds, setMilliseconds] = useState(String(record.real_ms));
  const [ticks, setTicks] = useState(String(record.ticks));
  return (
    <details>
      <summary>Correct record</summary>
      <form
        className="moderation-correction"
        onSubmit={(event) => {
          event.preventDefault();
          void onSave({ real_ms: Number(milliseconds), ticks: Number(ticks) });
        }}
      >
        <label>
          Time (ms){" "}
          <input
            type="number"
            value={milliseconds}
            onChange={(e) => setMilliseconds(e.target.value)}
            min={1}
            max={7200000}
            step={1}
            required
          />
        </label>
        <label>
          Ticks{" "}
          <input
            type="number"
            value={ticks}
            onChange={(e) => setTicks(e.target.value)}
            min={1}
            max={144000}
            step={1}
            required
          />
        </label>
        <button type="submit" disabled={disabled}>
          Save correction
        </button>
      </form>
    </details>
  );
}

type ChatReport = {
  id: string;
  uuid: string;
  reporter: string;
  reason: string;
  evidence: string;
};
function ChatReview({
  disabled,
  onSelect,
}: Readonly<{
  disabled: boolean;
  onSelect: (uuid: string, report: string) => Promise<void>;
}>) {
  const [reports, setReports] = useState<ChatReport[]>([]);
  const [reason, setReason] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const working = useRef(false);
  async function load() {
    setReports((await request<{ reports: ChatReport[] }>("chat")).reports);
  }
  async function act(body?: object) {
    if (working.current) return;
    working.current = true;
    setBusy(true);
    setError("");
    try {
      if (body) {
        await request("chat", { ...body, reason });
        setReason("");
      }
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Request failed");
    } finally {
      working.current = false;
      setBusy(false);
    }
  }
  return (
    <section className="moderation">
      <h2>Chat reports</h2>
      <button
        type="button"
        className="secondary"
        disabled={busy || disabled}
        onClick={() => void act()}
      >
        Refresh reports
      </button>
      {error && <p role="alert">{error}</p>}
      {reports.length > 0 && (
        <label>
          Review reason{" "}
          <input
            value={reason}
            maxLength={500}
            onChange={(e) => setReason(e.target.value)}
          />
        </label>
      )}
      <ul className="moderation-records">
        {reports.map((report) => (
          <li key={report.id}>
            <p>{report.reason}</p>
            <p>
              Reported by <code>{report.reporter}</code>
            </p>
            <pre>
              {JSON.stringify(JSON.parse(report.evidence) as unknown, null, 2)}
            </pre>
            <div className="moderation-actions">
              <button
                type="button"
                className="secondary"
                disabled={busy || disabled}
                onClick={() => void onSelect(report.uuid, report.id)}
              >
                Review player
              </button>
              <button
                type="button"
                className="secondary"
                disabled={busy || disabled || !reason.trim()}
                onClick={() =>
                  void act({ report_id: report.id, action: "hide" })
                }
              >
                Remove message
              </button>
              <button
                type="button"
                className="secondary"
                disabled={busy || disabled || !reason.trim()}
                onClick={() =>
                  void act({ report_id: report.id, action: "dismiss" })
                }
              >
                Dismiss report
              </button>
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}
