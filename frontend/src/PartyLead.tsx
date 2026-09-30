import { useEffect, useRef, useState } from "react";
import {
  andList,
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
  requirements,
  partyApi,
  type PartyState,
  type Role,
  type Rules,
  type Thresholds,
} from "./partyApi";

import {
  loadPartyRules,
  savePartyRules,
  resetPartyRules,
} from "./partyPreferences";

type Run = (task: () => Promise<PartyState>) => Promise<boolean>;
const EVERY = "every";
const DEFAULT_METRICS: Metric[] = ["catacombs", "s_plus_ms", "magical_power"];
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

  if (party.completed || party.full_since !== null)
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
            When the party fills, everyone has 5 minutes to get in game. The mod
            sends invites once everyone is online.
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
  onDone: (notice?: string) => void;
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
  const [initialRules] = useState(
    () => party?.rules ?? loadPartyRules(state.you.uuid, initialFloor),
  );
  const [draft, setDraft] = useState<Draft>(() => draftFrom(initialRules));
  const [exempt, setExempt] = useState<Role[]>(initialRules.exempt);
  const drafts = useRef<
    Partial<Record<Floor, { draft: Draft; exempt: Role[] }>>
  >({});
  const heading = useRef<HTMLHeadingElement>(null);
  const form = useRef<HTMLFormElement>(null);
  const [memoryNotice, setMemoryNotice] = useState("");
  const [resetVersion, setResetVersion] = useState(0);
  useEffect(() => {
    heading.current?.focus();
  }, []);
  function changeFloor(next: Floor) {
    if (next === floor) return;
    drafts.current[floor] = { draft, exempt };
    const stored = loadPartyRules(state.you.uuid, next);
    const nextDraft = drafts.current[next] ?? {
      draft: draftFrom(stored),
      exempt: stored.exempt,
    };
    setDraft(nextDraft.draft);
    setExempt(nextDraft.exempt);
    setFloor(next);
    setProblem("");
    setMemoryNotice("");
  }
  function focusInvalid() {
    requestAnimationFrame(() => {
      const input = form.current?.querySelector<HTMLInputElement>(
        '[aria-invalid="true"]',
      );
      let parent = input?.parentElement;
      while (parent) {
        if (parent instanceof HTMLDetailsElement) parent.open = true;
        parent = parent.parentElement;
      }
      input?.focus();
    });
  }
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
          focusInvalid();
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
      focusInvalid();
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
    if (done) {
      const remembered = savePartyRules(state.you.uuid, floor, rules);
      onDone(
        remembered
          ? undefined
          : "Party saved. This browser could not remember your requirements.",
      );
    }
  };

  return (
    <form
      ref={form}
      className="party-form"
      aria-labelledby="form-title"
      onSubmit={(event) => {
        event.preventDefault();
        void submit();
      }}
    >
      <div className="form-heading">
        <h2 id="form-title" ref={heading} tabIndex={-1}>
          {mode === "create" ? "Create a party" : "Edit requirements"}
        </h2>
        <button type="button" className="text-button" onClick={() => onDone()}>
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
                onClick={() => changeFloor(entry)}
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
        <legend>Shared requirements</legend>
        <p className="quiet-label">
          For every open slot. Empty means no requirement.
        </p>
        <RequirementFields
          key={`shared-${floor}-${resetVersion}`}
          column={EVERY}
          draft={draft}
          onChange={setDraft}
        />
      </fieldset>
      <details
        className="form-disclosure"
        open={
          columns.some(
            (role) =>
              exempt.includes(role) ||
              METRIC_ORDER.some((metric) => draft[`${role}:${metric}`]),
          ) || undefined
        }
      >
        <summary>
          Class-specific requirements{" "}
          <span className="quiet-label">
            {columns.filter(
              (role) =>
                exempt.includes(role) ||
                METRIC_ORDER.some((metric) => draft[`${role}:${metric}`]),
            ).length || ""}
          </span>
        </summary>
        <p className="quiet-label">
          Class rules add to shared rules. The stricter value applies.
        </p>
        {columns.map((role) => {
          const current: Rules = {
            shared: {},
            per_class: { [role]: {} },
            exempt,
          };
          for (const metric of METRIC_ORDER) {
            const shared = parsed(`${EVERY}:${metric}`, metric),
              own = parsed(`${role}:${metric}`, metric);
            if (shared !== null && shared !== undefined)
              current.shared[metric] = shared;
            if (own !== null && own !== undefined)
              current.per_class[role]![metric] = own;
          }
          const active =
            exempt.includes(role) ||
            METRIC_ORDER.some((metric) => draft[`${role}:${metric}`]);
          return (
            <details
              key={`${floor}-${role}-${resetVersion}`}
              className="class-requirements"
              open={active || undefined}
            >
              <summary>
                {CLASS_NAMES[role]}{" "}
                <span className="quiet-label">
                  {rulesText(Object.fromEntries(requirements(current, role))) ||
                    "No requirements"}
                </span>
              </summary>
              <label className="check-field">
                <input
                  type="checkbox"
                  checked={exempt.includes(role)}
                  onChange={(e) =>
                    setExempt(
                      e.target.checked
                        ? [...exempt, role]
                        : exempt.filter((value) => value !== role),
                    )
                  }
                />
                Skip shared Catacombs requirement for {CLASS_NAMES[role]}
              </label>
              <RequirementFields
                column={role}
                draft={draft}
                onChange={setDraft}
              />
            </details>
          );
        })}
      </details>
      <div className="preference-actions">
        <span className="quiet-label">
          Remembers {floor} requirements after a successful save.
        </span>
        <button
          type="button"
          className="text-button"
          onClick={() => {
            const removed = resetPartyRules(state.you.uuid, floor);
            setResetVersion((value) => value + 1);
            setDraft({});
            setExempt([]);
            delete drafts.current[floor];
            setMemoryNotice(
              removed
                ? `Cleared saved ${floor} requirements.`
                : "Requirements cleared, but browser storage is unavailable.",
            );
          }}
        >
          Reset saved requirements
        </button>
      </div>
      {memoryNotice && (
        <p role="status">
          {memoryNotice}{" "}
          <button type="button" onClick={() => onDone()}>
            Done
          </button>
        </p>
      )}
      <details className="form-disclosure" open={kept.length > 0 || undefined}>
        <summary>
          Blocked players {kept.length > 0 ? `(${kept.length})` : ""}
        </summary>
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
      </details>
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

function RequirementFields({
  column,
  draft,
  onChange,
}: {
  column: string;
  draft: Draft;
  onChange: (value: Draft) => void;
}) {
  const [added, setAdded] = useState<Metric[]>([]);
  const visible = [
    ...DEFAULT_METRICS,
    ...METRIC_ORDER.filter(
      (metric) =>
        !DEFAULT_METRICS.includes(metric) &&
        (added.includes(metric) || Boolean(draft[`${column}:${metric}`])),
    ),
  ];
  const label =
    column === EVERY ? "every open slot" : CLASS_NAMES[column as Role];
  return (
    <>
      <div className="requirement-fields">
        {visible.map((metric) => {
          const key = `${column}:${metric}`,
            invalid = parseMetric(metric, draft[key] ?? "") === undefined;
          return (
            <label key={metric} className="stack-field">
              <span>{METRICS[metric].label}</span>
              <span className="quiet-label">{HINT[metric]}</span>
              <input
                aria-label={`${METRICS[metric].label}, ${label}`}
                value={draft[key] ?? ""}
                inputMode={METRICS[metric].unit === "time" ? "text" : "decimal"}
                placeholder={METRICS[metric].unit === "time" ? "m:ss" : "Any"}
                aria-invalid={invalid}
                aria-describedby={invalid ? `error-${key}` : undefined}
                onChange={(e) => onChange({ ...draft, [key]: e.target.value })}
              />
              {invalid && (
                <span id={`error-${key}`} className="field-error">
                  {METRICS[metric].unit === "time"
                    ? "Use m:ss, up to 120:00."
                    : `Enter a valid value up to ${inputValue(metric, METRICS[metric].max)}.`}
                </span>
              )}
            </label>
          );
        })}
      </div>
      {visible.length < METRIC_ORDER.length && (
        <label className="add-requirement">
          Add requirement for {label}
          <select
            value=""
            onChange={(e) => setAdded([...added, e.target.value as Metric])}
          >
            <option value="" disabled>
              Choose a record…
            </option>
            {METRIC_ORDER.filter((metric) => !visible.includes(metric)).map(
              (metric) => (
                <option key={metric} value={metric}>
                  {METRICS[metric].label}
                </option>
              ),
            )}
          </select>
        </label>
      )}
    </>
  );
}
