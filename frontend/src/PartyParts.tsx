import type { ReactNode } from "react";
import { PartyPlayerName } from "./PlayerCard";
import {
  CLASS_NAMES,
  type Detail,
  type Floor,
  formatMetric,
  formatRule,
  meets,
  METRIC_ORDER,
  METRICS,
  type PartyState,
  type Role,
  requirements,
  type Stats,
  statValue,
  useCountdown,
} from "./partyApi";

export type ChipKind = "filled" | "open" | "fit" | "miss" | "you";
export type Chip = { role: Role; kind: ChipKind; label: string };

const LETTER: Record<Role, string> = {
  archer: "A",
  berserk: "B",
  healer: "H",
  mage: "M",
  tank: "T",
};

export function orList(roles: Role[]) {
  return roles.map((role) => CLASS_NAMES[role]).join(" or ");
}

export function andList(roles: Role[]) {
  const names = roles.map((role) => CLASS_NAMES[role]);
  return names.length > 1
    ? `${names.slice(0, -1).join(", ")} and ${names.at(-1)}`
    : (names[0] ?? "");
}

export function ClassTile({
  role,
  kind,
}: Readonly<{ role: Role; kind: ChipKind }>) {
  return (
    <span className={`chip chip-${kind}`} aria-hidden="true">
      {LETTER[role]}
    </span>
  );
}

export function Roster({
  chips,
  label = "Roster",
}: Readonly<{
  chips: Chip[];
  label?: string;
}>) {
  return (
    <ul className="roster" aria-label={label}>
      {chips.map((chip, index) => (
        <li key={index} className={`chip chip-${chip.kind}`} title={chip.label}>
          <span aria-hidden="true">{LETTER[chip.role]}</span>
          <span className="sr-only">{chip.label}</span>
        </li>
      ))}
    </ul>
  );
}

/** Tiles for a party the viewer is in: their own slot highlighted, open slots neutral. */
export function memberChips(party: Detail, you: string): Chip[] {
  return party.slots.map((slot, index) => {
    const member = party.members.find((entry) => entry.slot === index);
    if (!member)
      return {
        role: slot.role,
        kind: "open",
        label: `${CLASS_NAMES[slot.role]}, open`,
      };
    const mine = member.name === you;
    return {
      role: slot.role,
      kind: mine ? "you" : "filled",
      label: `${CLASS_NAMES[slot.role]}, ${mine ? "you" : member.name}`,
    };
  });
}

type Extra = (slot: number, role: Role) => ReactNode;

function tileKind(mine: boolean, filled: boolean): ChipKind {
  if (mine) return "you";
  return filled ? "filled" : "open";
}

/**
 * Members with their stats; open slots show each rule's threshold and, for classes
 * the viewer plays, the viewer's own value.
 */
export function DetailTable({
  party,
  floor,
  you,
  stats,
  playing = [],
  renderOpenNote,
  renderAction,
}: Readonly<{
  party: Detail;
  floor: Floor;
  you: string;
  stats: Stats | null;
  playing?: Role[];
  renderOpenNote?: Extra;
  renderAction?: Extra;
}>) {
  const metrics = METRIC_ORDER.filter(
    (metric) =>
      ["catacombs", "class_level", "s_plus_ms"].includes(metric) ||
      party.slots.some((slot) =>
        requirements(party.rules, slot.role).some(([rule]) => rule === metric),
      ),
  );
  return (
    <div className="detail-table-wrap">
      <table className="detail-table">
        <caption className="sr-only">{party.leader}’s party roster</caption>
        <thead>
          <tr>
            <th scope="col">Slot</th>
            <th scope="col">Player</th>
            {metrics.map((metric) => (
              <th scope="col" key={metric}>
                {metric === "class_level" ? "Class lvl" : METRICS[metric].short}
              </th>
            ))}
            {renderAction && (
              <th scope="col">
                <span className="sr-only">Action</span>
              </th>
            )}
          </tr>
        </thead>
        <tbody>
          {party.slots.map((slot, index) => {
            const member = party.members.find((entry) => entry.slot === index);
            const mine = member?.name === you;
            const rules = new Map(requirements(party.rules, slot.role));
            const plays = !member && playing.includes(slot.role);
            return (
              <tr key={index} className={mine ? "is-you" : undefined}>
                <th scope="row">
                  <span className="slot-name">
                    <ClassTile
                      role={slot.role}
                      kind={tileKind(mine, Boolean(member))}
                    />
                    {CLASS_NAMES[slot.role]}
                  </span>
                </th>
                <td>
                  {member ? (
                    <span className="member-name">
                      <PartyPlayerName user={member} />
                      {mine && " (you)"}
                      {member.leader && <span className="tag">Leader</span>}
                    </span>
                  ) : (
                    <span className="open-slot">
                      Open
                      {renderOpenNote?.(index, slot.role)}
                    </span>
                  )}
                </td>
                {metrics.map((metric) => {
                  if (member) {
                    const value = member.stats?.[metric] ?? null;
                    return (
                      <td
                        key={metric}
                        className={value === null ? "muted" : undefined}
                      >
                        {formatMetric(metric, value)}
                      </td>
                    );
                  }
                  const threshold = rules.get(metric);
                  if (threshold === undefined)
                    return (
                      <td key={metric} className="muted">
                        any
                      </td>
                    );
                  const value = statValue(stats, metric, slot.role, floor);
                  const ok = meets(metric, threshold, value);
                  return (
                    <td key={metric}>
                      {formatRule(metric, threshold)}
                      {plays && (
                        <span className={`yours ${ok ? "ok" : "bad"}`}>
                          <span aria-hidden="true">{ok ? "✓" : "×"}</span> you{" "}
                          {formatMetric(metric, value)}
                          <span className="sr-only">
                            {ok ? ", meets it" : ", below it"}
                          </span>
                        </span>
                      )}
                    </td>
                  );
                })}
                {renderAction && (
                  <td className="row-action">
                    {renderAction(index, slot.role)}
                  </td>
                )}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

type FullPhase = "completed" | "invited" | "joining";

function fullPhase(party: {
  completed?: boolean;
  invited?: boolean;
}): FullPhase {
  if (party.completed) return "completed";
  return party.invited ? "invited" : "joining";
}

function fullTitle(inGame: boolean, waiting: string[]) {
  if (!inGame) return "Party full · get in game";
  return waiting.length
    ? `You’re in · waiting for ${waiting.join(", ")}`
    : "Everyone is in game";
}

function fullNextStep(phase: FullPhase, leader: string) {
  if (phase === "completed")
    return "This private party stays off the finder. Leave here when you’re done.";
  if (phase === "invited")
    return `Accept ${leader}’s invite in Minecraft. The leader can use /mithrilpfreinvite to invite missing players again.`;
  return "Once everyone is on Hypixel, the leader’s mod sends one round of invites. It won’t automatically retry.";
}

const FULL_FOOTER: Record<FullPhase, string> = {
  completed: "Leaving here does not leave your Minecraft party.",
  invited:
    "This listing stays hidden until everyone has joined the Minecraft party.",
  joining:
    "If you’re not in game when the timer ends, you’re removed from the party and can’t reserve or look for parties for an hour.",
};

/** The five-minute window after a party fills. */
export function FullPanel({
  state,
  onLeave,
  busy,
}: Readonly<{
  state: PartyState;
  onLeave: () => void;
  busy: boolean;
}>) {
  const party = state.party!;
  const left = useCountdown(party.join_deadline, state.server_time);
  const waiting = party.slots
    .map((_, index) => index)
    .filter((index) => !party.joined[index])
    .map((index) => party.members.find((entry) => entry.slot === index)?.name)
    .filter((name): name is string => Boolean(name));
  const inGame = party.joined.filter(Boolean).length;
  const minutes =
    left === null
      ? ""
      : `${Math.floor(left / 60)}:${String(left % 60).padStart(2, "0")}`;
  const phase = fullPhase(party);
  return (
    <section className="held-panel full-panel" aria-labelledby="full-title">
      <div className="held-heading">
        <h2 id="full-title" aria-live="polite">
          {party.completed
            ? "Your party"
            : fullTitle(state.you.in_game, waiting)}
        </h2>
        <span className="quiet-label">
          {party.floor} · {party.leader}’s party
        </span>
      </div>
      {phase === "completed" && (
        <p>Connected in Minecraft · chat stays open here.</p>
      )}
      {phase === "invited" && (
        <p>
          Invites requested · {party.accepted?.filter(Boolean).length ?? 0} of 5
          in the party
        </p>
      )}
      {phase === "joining" && (
        <p className="countdown">
          <span>{minutes}</span> left to join Hypixel · {inGame} of 5 in game
        </p>
      )}
      <ul className="in-game-list" aria-label="Who is in game">
        {party.slots.map((slot, index) => {
          const member = party.members.find((entry) => entry.slot === index);
          const joined = party.joined[index];
          return (
            <li
              key={index}
              className={member?.name === state.you.name ? "is-you" : undefined}
            >
              <ClassTile
                role={slot.role}
                kind={member?.name === state.you.name ? "you" : "filled"}
              />
              {member ? (
                <PartyPlayerName user={member} />
              ) : (
                CLASS_NAMES[slot.role]
              )}
              <span
                className={`presence-dot ${joined ? "on" : "off"}`}
                aria-hidden="true"
              />
              <span className="sr-only">
                {joined ? ", in game" : ", not in game yet"}
              </span>
            </li>
          );
        })}
      </ul>
      <p>{fullNextStep(phase, party.leader)}</p>
      <div className="held-footer">
        <p className="quiet-label">{FULL_FOOTER[phase]}</p>
        <button className="secondary" onClick={onLeave} disabled={busy}>
          Leave party
        </button>
      </div>
    </section>
  );
}
