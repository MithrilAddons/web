import { useState } from "react";
import {
  andList,
  ClassTile,
  DetailTable,
  FullPanel,
  memberChips,
  Roster,
} from "./PartyParts";
import {
  CLASS_NAMES,
  CLASSES,
  type Floor,
  FLOORS,
  formatRule,
  inputValue,
  type Metric,
  METRIC_ORDER,
  METRICS,
  openRoles,
  parseMetric,
  partyApi,
  type PartyState,
  type Role,
  type Rules,
  type Thresholds,
} from "./partyApi";

type Run = (task: () => Promise<PartyState>) => Promise<boolean>;
const EVERY = "every";
const HINT: Record<Metric, string> = {
  catacombs: "At least",
  class_level: "At least, for the slot’s class",
  magical_power: "At least, highest recorded",
  s_plus_ms: "At most, m:ss",
  solo_ms: "At most, m:ss, from the mod",
  terminals_ms: "At most, m:ss, from the mod",
  ss_ms: "At most, seconds. Last 20 F7/M7 runs",
};

function rulesText(thresholds: Thresholds) {
  return (Object.entries(thresholds) as [Metric, number][])
    .map(
      ([metric, value]) =>
        `${METRICS[metric].short} ${formatRule(metric, value)}`,
    )
    .join(" · ");
}

export function LeaderView({
  state,
  run,
  busy,
  onEdit,
}: {
  state: PartyState;
  run: Run;
  busy: boolean;
  onEdit: () => void;
}) {
  const party = state.party!;
  const [removing, setRemoving] = useState<number | null>(null);
  const [closing, setClosing] = useState(false);
  const open = openRoles(party);
  const matching = party.matching;

  if (party.full_since !== null)
    return (
      <FullPanel
        state={state}
        busy={busy}
        onLeave={() => void run(partyApi.leave)}
      />
    );

  return (
    <>
      <div className="lead-heading">
        <div>
          <h2>Your {party.floor} party</h2>
          <p className="quiet-label">
            <span
              className={`presence-dot ${party.paused ? "off" : "on"}`}
              aria-hidden="true"
            />{" "}
            {party.paused ? "Paused · hidden from players" : "Listed"} ·{" "}
            {5 - open.length} of 5 held
            {open.length > 0 && ` · waiting for ${andList(open)}`}
          </p>
        </div>
        <div className="lead-actions">
          <button
            className="secondary"
            disabled={busy}
            onClick={() => void run(() => partyApi.pause(!party.paused))}
          >
            {party.paused ? "Resume listing" : "Pause listing"}
          </button>
          <button className="secondary" disabled={busy} onClick={onEdit}>
            Edit requirements
          </button>
          {closing ? (
            <>
              <button
                className="danger"
                disabled={busy}
                onClick={() => void run(partyApi.unlist)}
              >
                Unlist and disband
              </button>
              <button className="text-button" onClick={() => setClosing(false)}>
                Keep it
              </button>
            </>
          ) : (
            <button
              className="text-button danger-text"
              onClick={() => setClosing(true)}
            >
              Unlist
            </button>
          )}
        </div>
      </div>
      <div className="lead-grid">
        <section className="party-panel" aria-labelledby="roster-title">
          <div className="panel-toolbar">
            <h3 id="roster-title">Roster</h3>
            <Roster chips={memberChips(party, state.you.name)} label="Slots" />
          </div>
          <DetailTable
            party={party}
            floor={party.floor}
            you={state.you.name}
            stats={null}
            openNote={(_, role) =>
              matching?.roles[role] && (
                <span className="accent small">
                  {" "}
                  · {matching.roles[role]!.qualify} looking qualify
                </span>
              )
            }
            action={(slot) => {
              const member = party.members.find((entry) => entry.slot === slot);
              if (!member || member.name === state.you.name) return null;
              if (removing !== slot)
                return (
                  <button
                    className="small-button"
                    onClick={() => setRemoving(slot)}
                  >
                    Remove…
                  </button>
                );
              return (
                <RemoveChoice
                  name={member.name}
                  busy={busy}
                  onCancel={() => setRemoving(null)}
                  onRemove={(block) =>
                    void run(() => partyApi.remove(member.uuid, block)).then(
                      () => setRemoving(null),
                    )
                  }
                />
              );
            }}
          />
          <p className="panel-message">
            When every slot is held, everyone has 5 minutes to get in game and
            your game invites each player as they come online. If you leave or
            disconnect, a random member with the website or mod open becomes
            leader. If nobody is online, the party disbands.
          </p>
        </section>
        <div className="lead-side">
          <section className="side-card" aria-labelledby="matching-title">
            <h3 id="matching-title">Matching now</h3>
            {matching ? (
              <>
                <p>
                  <strong>{matching.looking}</strong> players are looking for{" "}
                  {party.floor}.
                </p>
                <ul className="match-bars">
                  {open
                    .filter((role, index) => open.indexOf(role) === index)
                    .map((role) => {
                      const counts = matching.roles[role] ?? {
                        looking: 0,
                        qualify: 0,
                      };
                      const share = counts.looking
                        ? counts.qualify / counts.looking
                        : 0;
                      return (
                        <li key={role}>
                          <span>{CLASS_NAMES[role]}</span>
                          <span className="quiet-label">
                            {counts.qualify} of {counts.looking} qualify
                          </span>
                          <span className="bar" aria-hidden="true">
                            <span
                              style={{ width: `${Math.round(share * 100)}%` }}
                            />
                          </span>
                        </li>
                      );
                    })}
                </ul>
                <p className="quiet-label">
                  Counts only. “Qualify” means they meet your rules and your
                  team’s average S+ PB is within their limit. Updated about once
                  a minute.
                </p>
              </>
            ) : (
              <p className="quiet-label">Counting players who are looking…</p>
            )}
          </section>
          <section className="side-card" aria-labelledby="rules-title">
            <h3 id="rules-title">Requirements</h3>
            <dl className="rules-list">
              <div>
                <dt>Every slot</dt>
                <dd>{rulesText(party.rules.shared) || "None"}</dd>
              </div>
              {CLASSES.filter((role) => party.rules.per_class[role]).map(
                (role) => (
                  <div key={role}>
                    <dt>{CLASS_NAMES[role]}</dt>
                    <dd>{rulesText(party.rules.per_class[role]!)}</dd>
                  </div>
                ),
              )}
              {party.rules.exempt.length > 0 && (
                <div>
                  <dt>No Catacombs rule</dt>
                  <dd>
                    {party.rules.exempt
                      .map((role) => CLASS_NAMES[role])
                      .join(", ")}
                  </dd>
                </div>
              )}
              <div>
                <dt>Blocked</dt>
                <dd>
                  {party.blocked?.length
                    ? party.blocked.map((entry) => entry.name).join(", ")
                    : "Nobody"}
                </dd>
              </div>
            </dl>
            <p className="quiet-label">
              Edits apply right away. Players already in keep their slots, even
              if they no longer qualify. Remove them yourself if needed.
            </p>
          </section>
        </div>
      </div>
    </>
  );
}

function RemoveChoice({
  name,
  busy,
  onRemove,
  onCancel,
}: {
  name: string;
  busy: boolean;
  onRemove: (block: boolean) => void;
  onCancel: () => void;
}) {
  return (
    <span className="remove-choice" role="group" aria-label={`Remove ${name}`}>
      <button
        className="small-button"
        disabled={busy}
        onClick={() => onRemove(false)}
      >
        Remove
      </button>
      <button
        className="small-button danger"
        disabled={busy}
        onClick={() => onRemove(true)}
      >
        Remove and block
      </button>
      <button className="text-button small" onClick={onCancel}>
        Cancel
      </button>
    </span>
  );
}

type Draft = Record<string, string>;

function draftFrom(rules: Rules): Draft {
  const draft: Draft = {};
  for (const [metric, value] of Object.entries(rules.shared) as [
    Metric,
    number,
  ][])
    draft[`${EVERY}:${metric}`] = inputValue(metric, value);
  for (const role of CLASSES)
    for (const [metric, value] of Object.entries(
      rules.per_class[role] ?? {},
    ) as [Metric, number][])
      draft[`${role}:${metric}`] = inputValue(metric, value);
  return draft;
}

export function PartyForm({
  mode,
  state,
  floor: initialFloor,
  run,
  busy,
  onDone,
}: {
  mode: "create" | "edit";
  state: PartyState;
  floor: Floor;
  run: Run;
  busy: boolean;
  onDone: () => void;
}) {
  const party = mode === "edit" ? state.party : null;
  const leaderSlot = party?.members.find(
    (member) => member.name === state.you.name,
  )?.slot;
  const [floor, setFloor] = useState<Floor>(party?.floor ?? initialFloor);
  const [leaderClass, setLeaderClass] = useState<Role>(
    party && leaderSlot !== undefined ? party.slots[leaderSlot]!.role : "mage",
  );
  const [duplicates, setDuplicates] = useState(false);
  const [roles, setRoles] = useState<Role[]>(
    party ? party.slots.map((slot) => slot.role) : [...CLASSES],
  );
  const [draft, setDraft] = useState<Draft>(() =>
    party ? draftFrom(party.rules) : {},
  );
  const [exempt, setExempt] = useState<Role[]>(party?.rules.exempt ?? []);
  const [kept, setKept] = useState(party?.blocked ?? []);
  const [names, setNames] = useState("");
  const [problem, setProblem] = useState("");

  const slotRoles = party || duplicates ? roles : [...CLASSES];
  const leaderIndex = party
    ? (leaderSlot ?? 0)
    : slotRoles.indexOf(leaderClass);
  const columns = [
    ...new Set(slotRoles.filter((_, index) => index !== leaderIndex)),
  ] as Role[];
  const parsed = (key: string, metric: Metric) =>
    parseMetric(metric, draft[key] ?? "");
  const newNames = names.split(/[\s,]+/).filter(Boolean);
  const badName = newNames.find((name) => !/^[A-Za-z0-9_]{1,16}$/.test(name));

  const submit = async () => {
    const rules: Rules = { shared: {}, per_class: {}, exempt };
    for (const column of [EVERY, ...columns])
      for (const metric of METRIC_ORDER) {
        const value = parsed(`${column}:${metric}`, metric);
        if (value === undefined) {
          setProblem(
            `Check ${METRICS[metric].label} for ${column === EVERY ? "every slot" : CLASS_NAMES[column as Role]}.`,
          );
          return;
        }
        if (value === null) continue;
        if (column === EVERY) rules.shared[metric] = value;
        else (rules.per_class[column as Role] ??= {})[metric] = value;
      }
    if (badName) {
      setProblem(`“${badName}” isn’t a valid Minecraft name.`);
      return;
    }
    if (duplicates && !roles.includes(leaderClass)) {
      setProblem("One slot must be your class.");
      return;
    }
    setProblem("");
    const done =
      mode === "create"
        ? await run(() =>
            partyApi.publish({
              version: 1,
              floor,
              leader_class: leaderClass,
              roles: slotRoles,
              allow_duplicates: duplicates,
              rules,
              block_names: newNames,
            }),
          )
        : await run(() =>
            partyApi.edit(
              rules,
              kept.map((entry) => entry.uuid),
              newNames,
            ),
          );
    if (done) onDone();
  };

  return (
    <form
      className="party-form"
      aria-labelledby="form-title"
      onSubmit={(event) => {
        event.preventDefault();
        void submit();
      }}
    >
      <div className="form-heading">
        <h2 id="form-title">
          {mode === "create" ? "Create a party" : "Edit requirements"}
        </h2>
        <button type="button" className="text-button" onClick={onDone}>
          Cancel
        </button>
      </div>

      {mode === "create" && (
        <fieldset className="form-section form-inline">
          <legend className="sr-only">Floor and class</legend>
          <div className="segmented" role="group" aria-label="Floor">
            {FLOORS.map((entry) => (
              <button
                type="button"
                key={entry}
                aria-pressed={floor === entry}
                onClick={() => setFloor(entry)}
              >
                {entry}
              </button>
            ))}
          </div>
          <label className="stack-field">
            Your class
            <select
              value={leaderClass}
              onChange={(event) => setLeaderClass(event.target.value as Role)}
            >
              {CLASSES.map((role) => (
                <option key={role} value={role}>
                  {CLASS_NAMES[role]}
                </option>
              ))}
            </select>
          </label>
          <label className="check-field">
            <input
              type="checkbox"
              checked={duplicates}
              onChange={(event) => setDuplicates(event.target.checked)}
            />
            Allow duplicate classes
          </label>
        </fieldset>
      )}

      {mode === "create" && duplicates && (
        <fieldset className="form-section">
          <legend>Slots</legend>
          <div className="slot-picks">
            {roles.map((role, index) => (
              <label key={index} className="stack-field">
                Slot {index + 1}
                <select
                  value={role}
                  onChange={(event) =>
                    setRoles(
                      roles.map((entry, at) =>
                        at === index ? (event.target.value as Role) : entry,
                      ),
                    )
                  }
                >
                  {CLASSES.map((option) => (
                    <option key={option} value={option}>
                      {CLASS_NAMES[option]}
                    </option>
                  ))}
                </select>
              </label>
            ))}
          </div>
        </fieldset>
      )}

      <fieldset className="form-section">
        <legend>Requirements</legend>
        <p className="quiet-label">
          A joiner must meet every rule for their slot. Leave a field empty for
          no rule.
        </p>
        <div className="matrix-wrap">
          <table className="rule-matrix">
            <thead>
              <tr>
                <th scope="col">Rule</th>
                <th scope="col">Every open slot</th>
                {columns.map((role) => (
                  <th scope="col" key={role}>
                    <span className="slot-name">
                      <ClassTile role={role} kind="open" />
                      {CLASS_NAMES[role]}
                    </span>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {METRIC_ORDER.map((metric) => (
                <tr key={metric}>
                  <th scope="row">
                    {METRICS[metric].label}
                    <span className="quiet-label">{HINT[metric]}</span>
                  </th>
                  {[EVERY, ...columns].map((column) => {
                    const key = `${column}:${metric}`;
                    const label = `${METRICS[metric].label}, ${column === EVERY ? "every open slot" : CLASS_NAMES[column as Role]}`;
                    return (
                      <td key={column}>
                        <input
                          aria-label={label}
                          value={draft[key] ?? ""}
                          inputMode="numeric"
                          placeholder={
                            METRICS[metric].unit === "time" ? "m:ss" : "—"
                          }
                          aria-invalid={parsed(key, metric) === undefined}
                          onChange={(event) =>
                            setDraft({ ...draft, [key]: event.target.value })
                          }
                        />
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="exempt-row" role="group" aria-labelledby="exempt-label">
          <span id="exempt-label">Skip the Catacombs level for</span>
          {columns.map((role) => (
            <button
              type="button"
              key={role}
              className="class-toggle"
              aria-pressed={exempt.includes(role)}
              onClick={() =>
                setExempt(
                  exempt.includes(role)
                    ? exempt.filter((entry) => entry !== role)
                    : [...exempt, role],
                )
              }
            >
              <span className="class-letter" aria-hidden="true">
                {CLASS_NAMES[role][0]}
              </span>
              {CLASS_NAMES[role]}
            </button>
          ))}
          <span className="quiet-label">Their other rules still apply.</span>
        </div>
      </fieldset>

      <fieldset className="form-section">
        <legend>Blocked players</legend>
        <p className="quiet-label">
          Private to you. Blocked players never see your party, even after a
          rename.
        </p>
        {kept.length > 0 && (
          <ul className="blocked-list">
            {kept.map((entry) => (
              <li key={entry.uuid}>
                {entry.name}
                <button
                  type="button"
                  className="text-button"
                  aria-label={`Unblock ${entry.name}`}
                  onClick={() =>
                    setKept(kept.filter((item) => item.uuid !== entry.uuid))
                  }
                >
                  ×
                </button>
              </li>
            ))}
          </ul>
        )}
        <label className="stack-field blocked-names">
          Add Minecraft names, separated by spaces or commas
          <input
            value={names}
            aria-invalid={Boolean(badName)}
            onChange={(event) => setNames(event.target.value)}
          />
        </label>
      </fieldset>

      {problem && <p role="alert">{problem}</p>}
      <div className="form-footer">
        <button type="submit" className="primary" disabled={busy}>
          {mode === "create" ? "Publish party" : "Save requirements"}
        </button>
        <p className="quiet-label">
          {mode === "create"
            ? "You can edit it after publishing. Players already in keep their slots."
            : "Edits apply right away. Nobody is removed by an edit."}
        </p>
      </div>
    </form>
  );
}
