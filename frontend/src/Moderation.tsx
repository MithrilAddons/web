import { Children, useEffect, useRef, useState } from "react";
import { CuratorReview } from "./CuratorReview";
import { request } from "./moderationApi";
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
  const actionFocus = useRef<HTMLElement | null>(null);
  const [audit, setAudit] = useState<Audit[]>([]);
  const [view, setView] = useState<"players" | "reports" | "audit" | "curator">(
    "players",
  );
  const [pending, setPending] = useState<{
    path: string;
    body: Record<string, unknown>;
    target: string;
  } | null>(null);
  const [auditLoading, setAuditLoading] = useState(false);
  const [auditError, setAuditError] = useState("");
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

  useEffect(() => {
    if (!access || view !== "audit") return;
    let active = true;
    setAuditLoading(true);
    setAuditError("");
    void request<{ entries: Audit[] }>("audit")
      .then(
        (value) => {
          if (active) setAudit(value.entries);
        },
        (err: Error) => {
          if (active) setAuditError(err.message);
        },
      )
      .finally(() => {
        if (active) setAuditLoading(false);
      });
    return () => {
      active = false;
    };
  }, [Boolean(access), view]);

  async function perform(action: () => void | Promise<void>) {
    if (working.current) return;
    working.current = true;
    actionFocus.current =
      document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null;
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
    const value = query.trim().replaceAll("-", "");
    const identity = /^[0-9a-f]{32}$/i.test(value)
      ? { uuid: value.toLowerCase(), name: undefined }
      : await request<{ uuid: string; name: string }>(
          `resolve/${encodeURIComponent(query.trim())}`,
        );
    const data = await request<Player>(`player/${identity.uuid}`);
    setPlayer({ ...data, name: identity.name });
  }

  function mutate(path: string, body: Record<string, unknown>) {
    setPending({
      path,
      body,
      target: player?.name ?? player?.uuid ?? "Player",
    });
  }

  async function confirm(reason: string) {
    if (!pending) return;
    await request(pending.path, { ...pending.body, reason: reason.trim() });
    setPending(null);
    setNotice("Saved.");
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
      <title>Moderation · Mithril</title>
      <header>
        <h1 id="moderation-title">Moderation</h1>
        {access && <span className="quiet-label">{access.role}</span>}
      </header>
      {error && !pending && <p role="alert">{error}</p>}
      {notice && <output>{notice}</output>}
      {pending && (
        <ActionReview
          title={actionTitle(pending.path, pending.body)}
          target={pending.target}
          values={pending.body}
          busy={busy}
          returnFocus={actionFocus.current}
          error={error}
          onCancel={() => {
            setPending(null);
            setError("");
          }}
          onConfirm={(reason) => void perform(() => confirm(reason))}
        />
      )}
      {!access && !error && <output>Checking access…</output>}
      {access && (
        <>
          <nav className="moderation-tabs" aria-label="Moderation views">
            {(access.role === "owner"
              ? (["players", "reports", "audit", "curator"] as const)
              : (["players", "reports", "audit"] as const)
            ).map((item) => (
              <button
                key={item}
                aria-pressed={view === item}
                onClick={() => {
                  setView(item);
                  setError("");
                  setNotice("");
                }}
              >
                {
                  {
                    players: "Players & cases",
                    reports: "Chat reports",
                    audit: "Audit log",
                    curator: "Curator",
                  }[item]
                }
              </button>
            ))}
          </nav>
          <div className="content-stack" hidden={view !== "players"}>
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
                        {record.kind === "solo_clear"
                          ? "Soloclear"
                          : "Terminals"}{" "}
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
                              setEvidence(
                                await request(`evidence/${record.id}`),
                              ),
                            )
                          }
                        >
                          Evidence
                        </button>
                        <button
                          type="button"
                          className="secondary"
                          disabled={busy}
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
                          disabled={busy}
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
                    <EvidenceView value={evidence} />
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
                  <button type="submit" disabled={busy}>
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
                            disabled={busy}
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
                          disabled={busy}
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
                  <section className="content-stack">
                    <h3>Moderator access</h3>
                    <button
                      type="button"
                      className="secondary"
                      disabled={busy}
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
          </div>
          {view === "reports" && (
            <ChatReview
              disabled={busy}
              onSelect={async (uuid, reportId) => {
                await perform(async () => {
                  setPlayer(await request<Player>(`player/${uuid}`));
                  setQuery(uuid);
                  setReports([reportId]);
                  setSelected([]);
                  setView("players");
                  setEvidence(null);
                });
              }}
            />
          )}
          {view === "curator" && <CuratorReview />}
          {view === "audit" && (
            <section className="content-stack">
              <h2>Audit log</h2>
              {auditLoading && <output>Loading audit log…</output>}
              {auditError && <p role="alert">{auditError}</p>}
              {!auditLoading && !auditError && !audit.length && (
                <p>No moderator actions recorded.</p>
              )}
              <button
                type="button"
                className="secondary"
                disabled={busy}
                onClick={() =>
                  void perform(async () => {
                    setAuditError("");
                    setAudit(
                      (await request<{ entries: Audit[] }>("audit")).entries,
                    );
                  })
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
                      <h3>Before</h3>
                      <EvidenceView
                        value={JSON.parse(entry.before_json) as unknown}
                      />
                      <h3>After</h3>
                      <EvidenceView
                        value={JSON.parse(entry.after_json) as unknown}
                      />
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
          )}
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
  onSave: (value: { real_ms: number; ticks: number }) => void | Promise<void>;
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
  const [review, setReview] = useState<{
    report_id: string;
    action: string;
  } | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const working = useRef(false);
  useEffect(() => {
    let active = true;
    setBusy(true);
    void request<{ reports: ChatReport[] }>("chat")
      .then(
        (value) => {
          if (active) {
            setReports(value.reports);
            setLoaded(true);
          }
        },
        (err: Error) => {
          if (active) setError(err.message);
        },
      )
      .finally(() => {
        if (active) setBusy(false);
      });
    return () => {
      active = false;
    };
  }, []);
  async function load() {
    setReports((await request<{ reports: ChatReport[] }>("chat")).reports);
    setLoaded(true);
  }
  async function act(body?: object, reason?: string) {
    if (working.current) return;
    working.current = true;
    setBusy(true);
    setError("");
    try {
      if (body) {
        await request("chat", { ...body, reason });
        setReview(null);
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
    <section className="content-stack">
      <h2>Chat reports</h2>
      <button
        type="button"
        className="secondary"
        disabled={busy || disabled}
        onClick={() => void act()}
      >
        Refresh reports
      </button>
      {error && !review && <p role="alert">{error}</p>}
      {busy && !loaded && <output>Loading reports…</output>}
      {loaded && !busy && !error && !reports.length && (
        <p>No open chat reports.</p>
      )}
      {review && (
        <ActionReview
          title={review.action === "hide" ? "Remove message" : "Dismiss report"}
          target="Selected chat report"
          values={review}
          busy={busy}
          error={error}
          onCancel={() => setReview(null)}
          onConfirm={(reason) => void act(review, reason)}
        />
      )}
      <ul className="moderation-records">
        {reports.map((report) => (
          <li key={report.id}>
            <p>{report.reason}</p>
            <p>
              Reported by <code>{report.reporter}</code>
            </p>
            <EvidenceView value={JSON.parse(report.evidence) as unknown} />
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
                disabled={busy || disabled}
                onClick={() =>
                  setReview({ report_id: report.id, action: "hide" })
                }
              >
                Remove message
              </button>
              <button
                type="button"
                className="secondary"
                disabled={busy || disabled}
                onClick={() =>
                  setReview({ report_id: report.id, action: "dismiss" })
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

function actionTitle(path: string, body: Record<string, unknown>) {
  if (path === "sanction") {
    if (body.kind === "mute") return "Mute player";
    return body.kind === "network_ban" ? "Ban account and IP" : "Ban account";
  }
  if (path === "access")
    return body.enabled ? "Grant moderator access" : "Revoke moderator access";
  const action = typeof body.action === "string" ? body.action : path;
  return action.replaceAll("_", " ");
}

function ActionReview({
  title,
  target,
  values,
  busy,
  error,
  onCancel,
  onConfirm,
  returnFocus,
}: Readonly<{
  title: string;
  target: string;
  values: Record<string, unknown>;
  busy: boolean;
  error: string;
  onCancel: () => void;
  onConfirm: (reason: string) => void;
  returnFocus?: HTMLElement | null;
}>) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [reason, setReason] = useState("");
  useEffect(() => {
    const previous = returnFocus ?? document.activeElement;
    const overflow = document.body.style.overflow;
    const element = dialog.current!;
    element.showModal();
    element.querySelector("textarea")?.focus();
    document.body.style.overflow = "hidden";
    return () => {
      element.close();
      document.body.style.overflow = overflow;
      if (previous instanceof HTMLElement && previous.isConnected)
        previous.focus();
    };
  }, []);
  return (
    <dialog
      className="action-review"
      ref={dialog}
      aria-labelledby="action-review-title"
      onCancel={(event) => {
        event.preventDefault();
        if (!busy) onCancel();
      }}
    >
      <form
        onSubmit={(event) => {
          event.preventDefault();
          if (reason.trim()) onConfirm(reason);
        }}
      >
        <h2 id="action-review-title">{title}</h2>
        <p>{target}</p>
        {values.kind === "network_ban" && (
          <p>Other accounts using the same IP will also be blocked.</p>
        )}
        {"expires" in values && (
          <p>
            Ends:{" "}
            {values.expires === null
              ? "Permanent"
              : timestamp(values.expires as number)}
          </p>
        )}
        {Array.isArray(values.record_ids) && (
          <p>
            {values.record_ids.length} records and{" "}
            {Array.isArray(values.report_ids) ? values.report_ids.length : 0}{" "}
            reports attached as evidence.
          </p>
        )}
        {"real_ms" in values && (
          <p>
            Corrected time: {String(values.real_ms)} ms · {String(values.ticks)}{" "}
            ticks
          </p>
        )}
        <details>
          <summary>Action details</summary>
          <EvidenceView value={values} />
        </details>
        <label>
          <span>Reason</span>
          <textarea
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            required
            maxLength={500}
            rows={3}
            disabled={busy}
          />
        </label>
        {error && <p role="alert">{error}</p>}
        <div className="moderation-actions">
          <button
            className="primary"
            type="submit"
            disabled={busy || !reason.trim()}
          >
            {busy ? "Saving…" : "Confirm action"}
          </button>
          <button type="button" disabled={busy} onClick={onCancel}>
            Cancel
          </button>
        </div>
      </form>
    </dialog>
  );
}

function EvidenceView({ value }: Readonly<{ value: unknown }>) {
  if (value === null || value === undefined)
    return <span className="quiet-label">None</span>;
  if (Array.isArray(value))
    return value.length ? (
      <ul className="evidence-items">
        {Children.toArray(
          value.map((item) => (
            <li>
              <EvidenceView value={item} />
            </li>
          )),
        )}
      </ul>
    ) : (
      <span className="quiet-label">None</span>
    );
  if (typeof value === "object")
    return (
      <dl className="evidence-fields">
        {Object.entries(value).map(([key, item]) => (
          <div key={key}>
            <dt>{key.replaceAll("_", " ")}</dt>
            <dd>
              <EvidenceView value={item} />
            </dd>
          </div>
        ))}
      </dl>
    );
  if (typeof value === "boolean") return <span>{value ? "Yes" : "No"}</span>;
  if (typeof value === "string" || typeof value === "number")
    return <span>{value}</span>;
  return null;
}
