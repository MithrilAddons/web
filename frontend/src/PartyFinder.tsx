import { useEffect, useMemo, useRef, useState } from "react";
import { Account } from "./account";
import { ModDownload } from "./ModDownload";
import { PartyChat } from "./PartyChat";
import { LeaderView, PartyForm } from "./PartyLead";
import {
  andList,
  type Chip,
  DetailTable,
  FullPanel,
  memberChips,
  orList,
  Roster,
} from "./PartyParts";
import {
  CLASS_NAMES,
  CLASSES,
  type Detail,
  errorMessage,
  failures,
  type Floor,
  FLOORS,
  formatMetric,
  formatRule,
  formatTime,
  type Listing,
  METRICS,
  openRoles,
  parseMetric,
  partyApi,
  type PartyState,
  type Role,
  useListings,
  usePartyState,
} from "./partyApi";
import { chime, unlockSound } from "./sound";
import { PartyPlayerName } from "./PlayerCard";

type Run = (task: () => Promise<PartyState>) => Promise<boolean>;
type Sort = "fills" | "newest" | "team" | "reqs";
const SORTS: Record<Sort, string> = {
  fills: "Fills soonest",
  newest: "Newest",
  team: "Strongest team",
  reqs: "Lowest requirements",
};

export function PartyWorkspace() {
  const { state, signedOut, offline, apply } = usePartyState();
  const [view, setView] = useState<"browse" | "create" | "edit">("browse");
  const [preferredFloor, setFloor] = useState<Floor>("M7");
  const floor =
    state?.party?.floor ?? state?.you.looking?.floor ?? preferredFloor;
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [sound, setSound] = useState(true);
  const seen = useRef<Set<string> | null>(null);

  useEffect(() => {
    document.addEventListener("pointerdown", unlockSound, { once: true });
    document.addEventListener("keydown", unlockSound, { once: true });
    return () => {
      document.removeEventListener("pointerdown", unlockSound);
      document.removeEventListener("keydown", unlockSound);
    };
  }, []);

  useEffect(() => {
    if (!state) return;
    const ids = state.notices.map((notice) => notice.id);
    if (seen.current === null) {
      seen.current = new Set(ids);
      return;
    }
    for (const notice of state.notices) {
      if (seen.current.has(notice.id)) continue;
      seen.current.add(notice.id);
      if (sound && (notice.kind === "placed" || notice.kind === "party_full"))
        chime();
    }
  }, [state, sound]);

  const run: Run = async (task) => {
    setBusy(true);
    setError("");
    try {
      apply(await task());
      return true;
    } catch (reason) {
      setError(errorMessage(reason));
      return false;
    } finally {
      setBusy(false);
    }
  };

  let main;
  if (signedOut) main = <SignedOut />;
  else if (!state)
    main = (
      <p className="quiet-label" role="status">
        Loading parties…
      </p>
    );
  else if (view !== "browse")
    main = (
      <PartyForm
        mode={view}
        state={state}
        floor={floor}
        run={run}
        busy={busy}
        onDone={() => setView("browse")}
      />
    );
  else if (state.party?.you_lead)
    main = (
      <LeaderView
        state={state}
        run={run}
        busy={busy}
        onEdit={() => setView("edit")}
      />
    );
  else
    main = (
      <Browse
        state={state}
        floor={floor}
        setFloor={setFloor}
        run={run}
        busy={busy}
        sound={sound}
        setSound={setSound}
      />
    );

  return (
    <div className="workspace">
      <div className="party-main">
        {offline && (
          <p className="party-offline" role="status">
            Reconnecting to the party finder…
          </p>
        )}
        {state && <Notices state={state} />}
        {error && <p role="alert">{error}</p>}
        {main}
        {!signedOut && state?.party && (
          <PartyChat
            key={state.party.id}
            messages={state.party.messages ?? []}
            connected={!offline}
            onReport={async (messageId, reason) => {
              await partyApi.report(state.party!.id, messageId, reason);
            }}
            onSend={async (text, requestId) => {
              apply(await partyApi.chat(state.party!.id, text, requestId));
            }}
          />
        )}
      </div>
      <aside className="account-panel">
        <h2>Your account</h2>
        <Account />
        {state && (
          <MatchingRecords
            state={state}
            floor={floor}
            onCreate={
              !state.party && view === "browse"
                ? () => setView("create")
                : undefined
            }
          />
        )}
      </aside>
    </div>
  );
}

function SignedOut() {
  return (
    <section
      className="party-panel party-empty"
      aria-labelledby="parties-heading"
    >
      <h2 id="parties-heading">Parties</h2>
      <p>Link your Minecraft account to browse and join parties.</p>
      <ModDownload />
    </section>
  );
}

const NOTICE_TEXT: Record<string, string> = {
  "left_party:offline":
    "Your slot was released because this tab and Minecraft were both closed for a minute.",
  "left_party:removed": "The leader removed you from their party.",
  "left_party:no_show":
    "You were removed because you weren’t in game within 5 minutes of the party filling.",
  party_closed: "The leader closed the party.",
  "stopped_looking:offline":
    "You stopped looking because this tab and Minecraft were both closed for a minute.",
  leader_now: "The leader left. You now lead this party.",
};

function Notices({ state }: { state: PartyState }) {
  const [dismissed, setDismissed] = useState<Set<string>>(() => new Set());
  const recent = state.notices.filter(
    (notice) =>
      notice.at > state.server_time - 15 * 60 && !dismissed.has(notice.id),
  );
  const latest = [...recent].reverse().find((notice) => {
    const key = notice.reason ? `${notice.kind}:${notice.reason}` : notice.kind;
    return key in NOTICE_TEXT || notice.kind === "party_joined";
  });
  const banned = state.you.banned_until;
  return (
    <>
      {banned !== null && (
        <p className="party-notice is-bad" role="status">
          You can reserve or look for parties again in{" "}
          {Math.max(1, Math.ceil((banned - state.server_time) / 60))} min.
        </p>
      )}
      {latest && (
        <div className="party-notice" role="status">
          <p>
            {latest.kind === "party_joined"
              ? `Party formed: ${latest.roster?.map((entry) => entry.name).join(", ")}. Good luck!`
              : NOTICE_TEXT[
                  latest.reason
                    ? `${latest.kind}:${latest.reason}`
                    : latest.kind
                ]}
          </p>
          <button
            className="text-button"
            onClick={() => setDismissed(new Set([...dismissed, latest.id]))}
          >
            Dismiss
          </button>
        </div>
      )}
    </>
  );
}

function Browse({
  state,
  floor,
  setFloor,
  run,
  busy,
  sound,
  setSound,
}: {
  state: PartyState;
  floor: Floor;
  setFloor: (floor: Floor) => void;
  run: Run;
  busy: boolean;
  sound: boolean;
  setSound: (on: boolean) => void;
}) {
  const looking = state.you.looking;
  const party = state.party;
  const banned = state.you.banned_until !== null;
  const [draftClasses, setClasses] = useState<Role[]>(looking?.classes ?? []);
  const classes = looking?.classes ?? draftClasses;
  const [draftLimitText, setLimitText] = useState(
    looking?.limit ? formatTime(looking.limit) : "",
  );
  const limitText = looking
    ? looking.limit
      ? formatTime(looking.limit)
      : ""
    : draftLimitText;
  const [sort, setSort] = useState<Sort>("fills");
  const [expanded, setExpanded] = useState<string | null>(null);
  const [showOthers, setShowOthers] = useState(false);
  const { parties, failed } = useListings(floor, !party, state.state_version);
  const limit = parseMetric("s_plus_ms", limitText);
  const stats = state.you.stats;
  const selected = CLASSES.filter((role) => classes.includes(role));

  const rows = useMemo(
    () =>
      (parties ?? []).map((listing) => {
        const open = openRoles(listing);
        const fits = open.filter(
          (role) => failures(listing.rules, role, stats, floor).length === 0,
        );
        let reason = "";
        if (!fits.length) {
          if (!open.length) reason = "No open slots";
          else {
            const miss = failures(listing.rules, open[0]!, stats, floor)[0]!;
            reason = `${METRICS[miss.metric].short} ${formatRule(miss.metric, miss.threshold)} · you ${formatMetric(miss.metric, miss.value)}`;
          }
        }
        const average = listing.team.s_plus_ms_avg;
        const skipped =
          typeof limit === "number" && (average === null || average > limit);
        return { listing, open, fits, reason, skipped };
      }),
    [parties, stats, floor, limit],
  );
  const ordered = [...rows].sort((a, b) => {
    const x = a.listing;
    const y = b.listing;
    switch (sort) {
      case "fills":
        return (
          a.open.length - b.open.length ||
          (x.team.s_plus_ms_avg ?? Infinity) -
            (y.team.s_plus_ms_avg ?? Infinity)
        );
      case "newest":
        return y.created_at - x.created_at;
      case "team":
        return (y.team.catacombs_avg ?? 0) - (x.team.catacombs_avg ?? 0);
      case "reqs":
        return (
          (x.rules.shared.catacombs ?? 0) - (y.rules.shared.catacombs ?? 0)
        );
    }
  });
  const eligible = ordered.filter((row) => row.fits.length);
  const others = ordered.filter((row) => !row.fits.length);

  const toggleClass = (role: Role) =>
    setClasses(
      classes.includes(role)
        ? classes.filter((entry) => entry !== role)
        : [...classes, role],
    );
  const startLooking = () => {
    unlockSound();
    void run(() =>
      partyApi.look(floor, selected, typeof limit === "number" ? limit : null),
    );
  };

  // Holding a slot: the party is the whole page; searching resumes after leaving.
  if (party) return <HeldPanel state={state} run={run} busy={busy} />;

  const lookLine = banned
    ? ""
    : looking
      ? `Looking for ${looking.floor} as ${orList(looking.classes)}. You’ll be placed automatically${sound ? ", with a sound" : ""}. If this tab and Minecraft are both closed for 60 seconds, you stop looking.`
      : !selected.length
        ? "Pick classes for automatic matching, or reserve any eligible slot below."
        : "Start looking places you in the party closest to full that you qualify for and whose average S+ PB is within your limit. Ties go to the faster average. Keep this tab or Minecraft open while you look.";

  return (
    <>
      <section
        className={`search-bar${looking ? " is-looking" : ""}`}
        aria-label="Find a party"
      >
        <div className="search-row">
          <div className="segmented" role="group" aria-label="Floor">
            {FLOORS.map((entry) => (
              <button
                key={entry}
                aria-pressed={floor === entry}
                disabled={Boolean(looking)}
                onClick={() => setFloor(entry)}
              >
                {entry}
              </button>
            ))}
          </div>
          <div
            className="class-toggles"
            role="group"
            aria-label="Classes you can play"
          >
            <span className="quiet-label">Playing as</span>
            {CLASSES.map((role) => (
              <button
                key={role}
                className="class-toggle"
                aria-label={CLASS_NAMES[role]}
                aria-pressed={classes.includes(role)}
                disabled={Boolean(looking)}
                onClick={() => toggleClass(role)}
              >
                <span className="class-letter" aria-hidden="true">
                  {CLASS_NAMES[role][0]}
                </span>
                <span className="class-label">{CLASS_NAMES[role]}</span>
              </button>
            ))}
          </div>
          {looking ? (
            <button
              className="look-button is-looking"
              disabled={busy}
              onClick={() => void run(partyApi.stopLooking)}
            >
              <span className="looking-dot" aria-hidden="true" />
              Stop looking
            </button>
          ) : (
            <button
              className="primary look-button"
              disabled={
                busy ||
                !selected.length ||
                Boolean(party) ||
                banned ||
                limit === undefined
              }
              onClick={startLooking}
            >
              Start looking
            </button>
          )}
        </div>
        <div
          className="search-row team-row"
          role="group"
          aria-label="Party must have"
        >
          <span className="quiet-label">Party must have</span>
          <label className="inline-field">
            Average S+ PB ≤
            <input
              value={limitText}
              placeholder="m:ss"
              inputMode="numeric"
              aria-invalid={limit === undefined}
              disabled={Boolean(looking)}
              onChange={(event) => setLimitText(event.target.value)}
            />
          </label>
          <button
            className="sound-toggle"
            aria-pressed={sound}
            onClick={() => {
              unlockSound();
              setSound(!sound);
            }}
          >
            {sound ? "Sound on" : "Sound off"}
          </button>
        </div>
        {lookLine && <p className="look-line">{lookLine}</p>}
      </section>

      <section className="party-panel" aria-labelledby="parties-heading">
        <div className="panel-toolbar">
          <h2 id="parties-heading">Parties</h2>
          <span className="quiet-label">
            {parties
              ? `${parties.length} listed on ${floor}`
              : failed
                ? ""
                : "Loading…"}
          </span>
          <div className="legend" aria-hidden="true">
            <span>
              <i className="chip chip-filled" /> Filled
            </span>
            <span>
              <i className="chip chip-open" /> Open
            </span>
            <span>
              <i className="chip chip-fit" /> Open for you
            </span>
          </div>
          <label className="sort-field">
            Sort
            <select
              value={sort}
              onChange={(event) => setSort(event.target.value as Sort)}
            >
              {Object.entries(SORTS).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </label>
        </div>
        {failed && (
          <p className="panel-message">Couldn’t load parties. Retrying…</p>
        )}
        {parties && !parties.length && (
          <p className="panel-message">
            No {floor} parties are listed right now. Start looking to be placed
            as soon as one appears, or create your own.
          </p>
        )}
        {parties && parties.length > 0 && (
          <h3 className="group-heading">Open to you · {eligible.length}</h3>
        )}
        {eligible.map((row) => (
          <PartyRow
            key={row.listing.id}
            row={row}
            state={state}
            floor={floor}
            expanded={expanded === row.listing.id}
            onToggle={() =>
              setExpanded(expanded === row.listing.id ? null : row.listing.id)
            }
            run={run}
            busy={busy || banned}
          />
        ))}
        {others.length > 0 && (
          <>
            <button
              className="group-heading group-toggle"
              aria-expanded={showOthers}
              onClick={() => setShowOthers(!showOthers)}
            >
              Can’t join · {others.length}
              <span>{showOthers ? "Hide" : "Show why"}</span>
            </button>
            {showOthers &&
              others.map((row) => (
                <PartyRow
                  key={row.listing.id}
                  row={row}
                  state={state}
                  floor={floor}
                  expanded={expanded === row.listing.id}
                  onToggle={() =>
                    setExpanded(
                      expanded === row.listing.id ? null : row.listing.id,
                    )
                  }
                  run={run}
                  busy={busy || banned}
                />
              ))}
          </>
        )}
      </section>
    </>
  );
}

type Row = {
  listing: Listing;
  open: Role[];
  fits: Role[];
  reason: string;
  skipped: boolean;
};

function PartyRow({
  row,
  state,
  floor,
  expanded,
  onToggle,
  run,
  busy,
}: {
  row: Row;
  state: PartyState;
  floor: Floor;
  expanded: boolean;
  onToggle: () => void;
  run: Run;
  busy: boolean;
}) {
  const { listing, fits, reason, skipped } = row;
  const [detail, setDetail] = useState<Detail | null>(null);
  const [detailFailed, setDetailFailed] = useState(false);
  const version = JSON.stringify([listing.slots, listing.rules]);
  useEffect(() => {
    if (!expanded) return;
    const controller = new AbortController();
    setDetailFailed(false);
    partyApi.detail(listing.id, controller.signal).then(setDetail, () => {
      if (!controller.signal.aborted) setDetailFailed(true);
    });
    return () => controller.abort();
  }, [expanded, listing.id, version]);

  const filled = listing.slots.filter((slot) => slot.filled).length;
  const chips: Chip[] = listing.slots.map((slot) => {
    if (slot.filled)
      return {
        role: slot.role,
        kind: "filled",
        label: `${CLASS_NAMES[slot.role]}, filled`,
      };
    const ok = fits.includes(slot.role);
    return {
      role: slot.role,
      kind: ok ? "fit" : "miss",
      label: `${CLASS_NAMES[slot.role]}, open, ${ok ? "you qualify" : "you don’t qualify"}`,
    };
  });
  const shared = Object.entries(listing.rules.shared) as [
    keyof typeof METRICS,
    number,
  ][];
  const classRules = CLASSES.filter(
    (role) => Object.keys(listing.rules.per_class[role] ?? {}).length,
  );
  const minutes = Math.max(
    0,
    Math.round((state.server_time - listing.created_at) / 60),
  );
  const reserve = (role: Role) => {
    unlockSound();
    void run(() => partyApi.reserve(listing.id, role));
  };

  return (
    <div className={`party-row${expanded ? " is-expanded" : ""}`}>
      <div className="party-summary">
        <div className="party-leader">
          <button
            className="row-toggle"
            aria-expanded={expanded}
            aria-label={`Details for ${listing.leader}’s party`}
            onClick={onToggle}
          >
            <span className="chevron" aria-hidden="true" />
          </button>
          {listing.leader_uuid ? (
            <PartyPlayerName
              user={{ uuid: listing.leader_uuid, name: listing.leader }}
            />
          ) : (
            listing.leader
          )}
          <p className="quiet-label">
            {filled}/5
            {listing.team.catacombs_avg !== null &&
              ` · Cata ${Math.floor(listing.team.catacombs_avg)} avg`}
            {` · ${minutes}m`}
          </p>
        </div>
        <Roster chips={chips} />
        <p className="party-rules">
          {shared.map(([metric, value]) => (
            <span key={metric}>
              {METRICS[metric].short}{" "}
              <strong>{formatRule(metric, value)}</strong>
            </span>
          ))}
          {classRules.length > 0 && (
            <span className="accent">
              + {classRules.map((role) => CLASS_NAMES[role]).join(", ")} rule
              {classRules.length > 1 ? "s" : ""}
            </span>
          )}
          {!shared.length && !classRules.length && <span>No requirements</span>}
        </p>
        <div className="party-action">
          {fits.length === 1 && (
            <button
              className="primary"
              disabled={busy}
              onClick={() => reserve(fits[0]!)}
            >
              Reserve {CLASS_NAMES[fits[0]!]}
            </button>
          )}
          {fits.length > 1 && (
            <>
              <button disabled={busy} onClick={() => !expanded && onToggle()}>
                Choose slot
              </button>
              <span className="quiet-label">as {orList(fits)}</span>
            </>
          )}
          {skipped && fits.length > 0 && (
            <span
              className="bad small"
              title="Start looking won’t place you here. You can still reserve it yourself."
            >
              Skipped · S+ avg{" "}
              {listing.team.s_plus_ms_avg === null
                ? "unknown"
                : formatTime(listing.team.s_plus_ms_avg)}
            </span>
          )}
          {reason && (
            <span className="bad">
              <span aria-hidden="true">× </span>
              {reason}
            </span>
          )}
        </div>
      </div>
      {expanded && (
        <div className="party-detail">
          {detailFailed && <p role="alert">Couldn’t load this party.</p>}
          {!detail && !detailFailed && (
            <p className="quiet-label">Loading party…</p>
          )}
          {detail && (
            <DetailTable
              party={detail}
              floor={floor}
              you={state.you.name}
              stats={state.you.stats}
              playing={[...CLASSES]}
              action={(slot, role) =>
                fits.includes(role) &&
                !detail.members.some((member) => member.slot === slot) && (
                  <button
                    className="primary small-button"
                    disabled={busy}
                    aria-label={`Reserve ${CLASS_NAMES[role]} in ${listing.leader}’s party`}
                    onClick={() => reserve(role)}
                  >
                    Reserve
                  </button>
                )
              }
            />
          )}
          <p className="quiet-label">
            Every open slot must meet the shared rules plus its class rules. —
            means no mod data. Once all five slots are held, everyone has 5
            minutes to get in game.
          </p>
        </div>
      )}
    </div>
  );
}

function HeldPanel({
  state,
  run,
  busy,
}: {
  state: PartyState;
  run: Run;
  busy: boolean;
}) {
  const party = state.party!;
  const leave = () => void run(partyApi.leave);
  if (party.completed || party.full_since !== null)
    return <FullPanel state={state} onLeave={leave} busy={busy} />;
  const mine = party.members.find((member) => member.name === state.you.name);
  const role = mine ? party.slots[mine.slot]!.role : null;
  const joinedBy = [...state.notices]
    .reverse()
    .find(
      (notice) =>
        notice.party === party.id &&
        (notice.kind === "placed" || notice.kind === "reserved"),
    );
  const open = openRoles(party);
  return (
    <section className="held-panel" aria-labelledby="held-title">
      <div className="held-heading">
        <Roster chips={memberChips(party, state.you.name)} />
        <div>
          <h2 id="held-title">
            {joinedBy?.kind === "placed" && role
              ? `Placed in ${party.leader}’s party as ${CLASS_NAMES[role]}`
              : `${role ? `${CLASS_NAMES[role]} slot` : "Slot"} held in ${party.leader}’s party`}
          </h2>
          <p className="quiet-label">
            {party.floor} · {5 - open.length} of 5 held · waiting for{" "}
            {andList(open)}
          </p>
        </div>
        <button className="secondary" disabled={busy} onClick={leave}>
          Leave slot
        </button>
      </div>
      <DetailTable
        party={party}
        floor={party.floor}
        you={state.you.name}
        stats={state.you.stats}
      />
      <ul className="held-notes">
        <li>
          When the last slot fills, everyone has{" "}
          <strong>5 minutes to get in game</strong>. {party.leader}’s game sends
          one round of invites once everyone is online.
        </li>
        <li>
          Keep this tab or Minecraft open while you wait. If both are closed for
          60 seconds, your slot is released (no ban). A sound plays when the
          party fills.
        </li>
        <li>
          If {party.leader} leaves or disconnects, a random member with the
          website or mod open becomes leader. If nobody is online, the party
          disbands.
        </li>
      </ul>
    </section>
  );
}

function MatchingRecords({
  state,
  floor,
  onCreate,
}: {
  state: PartyState;
  floor: Floor;
  onCreate?: () => void;
}) {
  const stats = state.you.stats;
  const rows: [string, string][] = stats
    ? [
        ["Catacombs", formatMetric("catacombs", stats.catacombs)],
        ["Magical Power", formatMetric("magical_power", stats.magical_power)],
        ["S+ PB", formatMetric("s_plus_ms", stats.s_plus_ms[floor])],
        ["Solo clear PB", formatMetric("solo_ms", stats.solo_ms[floor])],
        [
          "Terminals PB",
          formatMetric("terminals_ms", stats.terminals_ms[floor]),
        ],
        ["SS average", formatMetric("ss_ms", stats.ss_ms)],
      ]
    : [];
  return (
    <section className="matching-records" aria-labelledby="records-title">
      <p className="presence">
        <span
          className={`presence-dot ${state.you.in_game ? "on" : "off"}`}
          aria-hidden="true"
        />
        {state.you.in_game ? "In game · mod connected" : "Not in game"}
      </p>
      <h3 id="records-title">Your {floor} records</h3>
      {stats ? (
        <>
          <dl>
            {rows.map(([label, value]) => (
              <div key={label}>
                <dt>{label}</dt>
                <dd>{value}</dd>
              </div>
            ))}
          </dl>
          <ul className="class-levels" aria-label="Class levels">
            {CLASSES.map((role) => (
              <li key={role}>
                <span aria-hidden="true">{CLASS_NAMES[role][0]}</span>
                <span className="sr-only">{CLASS_NAMES[role]}</span>
                {formatMetric("class_level", stats.class_levels[role])}
              </li>
            ))}
          </ul>
          <p className="quiet-label">
            Solo, terminal and SS times come from the mod. The rest comes from
            your selected Hypixel profile.
          </p>
        </>
      ) : (
        <p className="quiet-label">Loading your Hypixel stats…</p>
      )}
      {onCreate && (
        <button className="secondary create-button" onClick={onCreate}>
          Create a party
        </button>
      )}
    </section>
  );
}
