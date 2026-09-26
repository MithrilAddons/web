import { useCallback, useEffect, useRef, useState } from "react";

export const CLASSES = ["archer", "berserk", "healer", "mage", "tank"] as const;
export type Role = (typeof CLASSES)[number];
export const FLOORS = ["M7", "F7"] as const;
export type Floor = (typeof FLOORS)[number];
export const CLASS_NAMES: Record<Role, string> = {
  archer: "Archer",
  berserk: "Berserk",
  healer: "Healer",
  mage: "Mage",
  tank: "Tank",
};

export type Metric =
  | "catacombs"
  | "class_level"
  | "magical_power"
  | "s_plus_ms"
  | "solo_ms"
  | "terminals_ms"
  | "ss_ms";
type Unit = "level" | "count" | "time" | "seconds";
export const METRICS: Record<
  Metric,
  { label: string; short: string; min: boolean; unit: Unit; max: number }
> = {
  catacombs: {
    label: "Catacombs",
    short: "Cata",
    min: true,
    unit: "level",
    max: 1000,
  },
  class_level: {
    label: "Class level",
    short: "Class",
    min: true,
    unit: "level",
    max: 50,
  },
  magical_power: {
    label: "Magical Power",
    short: "MP",
    min: true,
    unit: "count",
    max: 10000,
  },
  s_plus_ms: {
    label: "S+ PB",
    short: "S+",
    min: false,
    unit: "time",
    max: 7_200_000,
  },
  solo_ms: {
    label: "Solo clear PB",
    short: "Solo",
    min: false,
    unit: "time",
    max: 7_200_000,
  },
  terminals_ms: {
    label: "Terminals PB",
    short: "Terms",
    min: false,
    unit: "time",
    max: 7_200_000,
  },
  ss_ms: {
    label: "SS average",
    short: "SS avg",
    min: false,
    unit: "seconds",
    max: 20_000,
  },
};
export const METRIC_ORDER = Object.keys(METRICS) as Metric[];

export type Thresholds = Partial<Record<Metric, number>>;
export type Rules = {
  shared: Thresholds;
  per_class: Partial<Record<Role, Thresholds>>;
  exempt: Role[];
};
export type Stats = {
  catacombs: number | null;
  class_levels: Record<Role, number | null>;
  magical_power: number | null;
  s_plus_ms: Record<Floor, number | null>;
  solo_ms: Record<Floor, number | null>;
  terminals_ms: Record<Floor, number | null>;
  ss_ms: number | null;
};
export type MemberStats = Record<Metric, number | null>;
export type Listing = {
  id: string;
  floor: Floor;
  leader: string;
  leader_uuid?: string;
  created_at: number;
  slots: { role: Role; filled: boolean }[];
  rules: Rules;
  team: { catacombs_avg: number | null; s_plus_ms_avg: number | null };
};
export type Member = {
  slot: number;
  uuid: string;
  name: string;
  leader: boolean;
  stats: MemberStats | null;
};
export type Detail = Listing & { members: Member[] };
export type Notice = {
  id: string;
  kind: string;
  at: number;
  party?: string;
  role?: Role;
  reason?: string;
  name?: string;
  roster?: { name: string; role: Role }[];
};
export type PartyView = Detail & {
  paused: boolean;
  full_since: number | null;
  join_deadline: number | null;
  joined: boolean[];
  invited?: boolean;
  accepted?: boolean[];
  you_lead: boolean;
  blocked?: { uuid: string; name: string }[];
  matching?: {
    looking: number;
    roles: Partial<Record<Role, { looking: number; qualify: number }>>;
  } | null;
};
export type Looking = {
  floor: Floor;
  classes: Role[];
  limit: number | null;
  since: number;
};
export type PartyState = {
  version: 1;
  state_id?: string;
  state_version: number;
  server_time: number;
  you: {
    uuid: string;
    name: string;
    in_game: boolean;
    banned_until: number | null;
    looking: Looking | null;
    stats: Stats | null;
  };
  notices: Notice[];
  party: PartyView | null;
};

// -- rules, mirrored from the server so each viewer computes its own eligibility ----

export function requirements(rules: Rules, role: Role): [Metric, number][] {
  const result = new Map<Metric, number>();
  for (const [metric, value] of Object.entries(rules.shared) as [
    Metric,
    number,
  ][]) {
    if (metric === "catacombs" && rules.exempt.includes(role)) continue;
    result.set(metric, value);
  }
  for (const [metric, value] of Object.entries(rules.per_class[role] ?? {}) as [
    Metric,
    number,
  ][]) {
    const current = result.get(metric);
    const stricter = METRICS[metric].min ? Math.max : Math.min;
    result.set(
      metric,
      current === undefined ? value : stricter(current, value),
    );
  }
  return METRIC_ORDER.filter((metric) => result.has(metric)).map((metric) => [
    metric,
    result.get(metric)!,
  ]);
}

export function statValue(
  stats: Stats | null,
  metric: Metric,
  role: Role,
  floor: Floor,
): number | null {
  if (!stats) return null;
  switch (metric) {
    case "class_level":
      return stats.class_levels[role];
    case "s_plus_ms":
    case "solo_ms":
    case "terminals_ms":
      return stats[metric][floor];
    default:
      return stats[metric];
  }
}

export function meets(metric: Metric, threshold: number, value: number | null) {
  if (value === null || value <= 0) return false;
  return METRICS[metric].min ? value >= threshold : value <= threshold;
}

export function failures(
  rules: Rules,
  role: Role,
  stats: Stats | null,
  floor: Floor,
) {
  return requirements(rules, role)
    .map(([metric, threshold]) => ({
      metric,
      threshold,
      value: statValue(stats, metric, role, floor),
    }))
    .filter(({ metric, threshold, value }) => !meets(metric, threshold, value));
}

export function openRoles(listing: Listing): Role[] {
  return listing.slots.filter((slot) => !slot.filled).map((slot) => slot.role);
}

// -- formatting and input parsing ----------------------------------------------------

export function formatTime(ms: number) {
  const seconds = Math.round(ms / 1000);
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
}

export function formatMetric(metric: Metric, value: number | null | undefined) {
  if (value === null || value === undefined) return "—";
  switch (METRICS[metric].unit) {
    case "level":
      return String(Math.floor(value));
    case "count":
      return Math.round(value).toLocaleString("en-US");
    case "time":
      return formatTime(value);
    case "seconds":
      return `${(value / 1000).toFixed(1)}s`;
  }
}

export function formatRule(metric: Metric, threshold: number) {
  return `${METRICS[metric].min ? "≥" : "≤"}${formatMetric(metric, threshold)}`;
}

/** Form text to a threshold: null when empty, undefined when invalid. */
export function parseMetric(
  metric: Metric,
  text: string,
): number | null | undefined {
  const value = text.trim();
  if (!value) return null;
  const { unit, max } = METRICS[metric];
  let parsed: number;
  if (unit === "time") {
    const match = /^(\d{1,3}):([0-5]\d)$/.exec(value);
    if (!match) return undefined;
    parsed = (Number(match[1]) * 60 + Number(match[2])) * 1000;
  } else if (unit === "seconds") {
    if (!/^\d{1,2}(\.\d)?$/.test(value)) return undefined;
    parsed = Math.round(Number(value) * 1000);
  } else {
    if (!/^\d{1,5}$/.test(value.replace(/,/g, ""))) return undefined;
    parsed = Number(value.replace(/,/g, ""));
  }
  return parsed >= 1 && parsed <= max ? parsed : undefined;
}

export function inputValue(metric: Metric, value: number | undefined) {
  if (value === undefined) return "";
  const { unit } = METRICS[metric];
  if (unit === "time") return formatTime(value);
  if (unit === "seconds") return (value / 1000).toFixed(1);
  return String(value);
}

// -- requests --------------------------------------------------------------------------

export class PartyRequestError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    readonly names: string[] = [],
  ) {
    super(code);
  }
}

const MESSAGES: Record<string, string> = {
  banned: "You can’t reserve or look for parties yet.",
  in_party: "You’re already in a party. Leave it first.",
  not_in_party: "You’re not in a party.",
  not_found: "That party is no longer listed.",
  party_full: "That party just filled up.",
  slot_taken: "Someone else took that slot.",
  not_eligible: "You no longer meet that slot’s requirements.",
  not_leader: "Only the leader can do that.",
  not_member: "That player is no longer in your party.",
  stats_unavailable:
    "Your Hypixel stats aren’t available yet. Try again in a minute.",
  capacity: "The party finder is busy. Try again shortly.",
  too_many_names: "Add at most 10 new names at a time.",
  name_lookup_unavailable: "Couldn’t look up those names. Try again shortly.",
  invalid_rules: "Check the requirement values.",
};

export function errorMessage(error: unknown) {
  if (error instanceof PartyRequestError) {
    if (error.code === "unknown_names")
      return `No Minecraft player named ${error.names.join(", ")}.`;
    if (error.status === 401) return "Your session ended. Sign in again.";
    return MESSAGES[error.code] ?? "Something went wrong. Try again.";
  }
  return "The party finder is unavailable. Try again shortly.";
}

async function call<T>(
  path: string,
  init: RequestInit & { json?: object } = {},
): Promise<T> {
  const { json, ...rest } = init;
  const response = await fetch(`/api/v1/party/${path}`, {
    method: json ? "POST" : "GET",
    headers: json ? { "Content-Type": "application/json" } : undefined,
    body: json ? JSON.stringify(json) : undefined,
    credentials: "same-origin",
    cache: "no-store",
    ...rest,
  });
  if (!response.ok) {
    let code = "";
    let names: string[] = [];
    try {
      const detail = ((await response.json()) as { detail?: unknown }).detail;
      if (typeof detail === "string") code = detail;
      else if (detail && typeof detail === "object" && "code" in detail) {
        code = String(detail.code);
        if ("names" in detail && Array.isArray(detail.names))
          names = detail.names.map(String);
      }
    } catch {
      // Error bodies are optional; the status is enough.
    }
    throw new PartyRequestError(response.status, code, names);
  }
  return response.json() as Promise<T>;
}

function checkState(value: unknown): PartyState {
  if (
    typeof value !== "object" ||
    value === null ||
    !("version" in value) ||
    value.version !== 1 ||
    !("state_version" in value) ||
    typeof value.state_version !== "number" ||
    !("you" in value) ||
    typeof value.you !== "object" ||
    !("notices" in value) ||
    !Array.isArray(value.notices)
  ) {
    throw new Error("Unsupported party state");
  }
  return value as PartyState;
}

const action = (path: string, json: object = {}) =>
  call<unknown>(path, { json, signal: AbortSignal.timeout(15000) }).then(
    checkState,
  );

export type PublishBody = {
  version: 1;
  floor: Floor;
  leader_class: Role;
  roles: Role[];
  allow_duplicates: boolean;
  rules: Rules;
  block_names: string[];
};

export const partyApi = {
  async state(
    known: number | undefined,
    signal: AbortSignal,
    stateId?: string,
  ) {
    const result = await call<unknown>("state", {
      json:
        known === undefined
          ? { version: 1 }
          : { version: 1, known, state_id: stateId },
      signal: AbortSignal.any([signal, AbortSignal.timeout(35_000)]),
    });
    if (
      typeof result === "object" &&
      result !== null &&
      "unchanged" in result &&
      result.unchanged === true
    )
      return null;
    return checkState(result);
  },
  look: (floor: Floor, classes: Role[], limit: number | null) =>
    action("look", { version: 1, floor, classes, max_team_s_plus_ms: limit }),
  stopLooking: () => action("stop-looking"),
  reserve: (partyId: string, role: Role) =>
    action("reserve", { party_id: partyId, role }),
  leave: () => action("leave"),
  publish: (body: PublishBody) => action("publish", body),
  edit: (rules: Rules, blocked: string[], blockNames: string[]) =>
    action("edit", { rules, blocked, block_names: blockNames }),
  pause: (paused: boolean) => action("pause", { paused }),
  unlist: () => action("unlist"),
  remove: (member: string, block: boolean) =>
    action("remove", { member, block }),
  async listings(floor: Floor, etag: string | null, signal: AbortSignal) {
    const response = await fetch(`/api/v1/party/listings?floor=${floor}`, {
      credentials: "same-origin",
      cache: "no-store",
      headers: etag ? { "If-None-Match": etag } : undefined,
      signal,
    });
    if (response.status === 304) return null;
    if (!response.ok) throw new PartyRequestError(response.status, "");
    const body = (await response.json()) as {
      version?: unknown;
      parties?: unknown;
    };
    if (body.version !== 1 || !Array.isArray(body.parties))
      throw new Error("Unsupported listings");
    return {
      etag: response.headers.get("ETag"),
      parties: body.parties as Listing[],
    };
  },
  detail: (id: string, signal: AbortSignal) =>
    call<Detail & { version: 1 }>(`listings/${encodeURIComponent(id)}`, {
      signal,
    }),
};

// -- live state ------------------------------------------------------------------------

/** Looking, holding a slot or leading: the site must count as open for the server. */
export function involved(state: PartyState | null) {
  return Boolean(state && (state.you.looking || state.party));
}

const IDLE_REFRESH = 5 * 60_000;

/**
 * Holds one state request open while involved (it doubles as the presence heartbeat);
 * otherwise fetches once and waits for the next action. Stale replies are ignored.
 */
export function usePartyState() {
  const [state, setState] = useState<PartyState | null>(null);
  const [signedOut, setSignedOut] = useState(false);
  const [offline, setOffline] = useState(false);
  const current = useRef<PartyState | null>(null);
  const retired = useRef(new Set<string>());
  const kick = useRef<() => void>(() => {});

  const apply = useCallback((next: PartyState) => {
    if (next.state_id && retired.current.has(next.state_id)) return;
    const previous = current.current;
    if (
      previous &&
      next.state_id === previous.state_id &&
      next.state_version < previous.state_version
    )
      return;
    if (previous?.state_id && next.state_id !== previous.state_id) {
      retired.current.add(previous.state_id);
      // Only recent generations can still have an in-flight response.
      if (retired.current.size > 64)
        retired.current.delete(retired.current.values().next().value!);
    }
    current.current = next;
    setState(next);
    kick.current();
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    let stopped = false;
    const pause = (ms: number) =>
      new Promise<void>((resolve) => {
        const done = () => {
          clearTimeout(timer);
          kick.current = () => {};
          resolve();
        };
        const timer = setTimeout(done, ms);
        kick.current = done;
      });
    void (async () => {
      let failed = 0;
      while (!stopped) {
        const known = involved(current.current)
          ? current.current!.state_version
          : undefined;
        try {
          const result = await partyApi.state(
            known,
            controller.signal,
            current.current?.state_id,
          );
          failed = 0;
          setOffline(false);
          if (result) apply(result);
          if (!involved(current.current)) await pause(IDLE_REFRESH);
        } catch (error) {
          if (stopped) return;
          if (error instanceof PartyRequestError && error.status === 401) {
            setSignedOut(true);
            return;
          }
          failed += 1;
          setOffline(true);
          await pause(Math.min(30_000, 1000 * 2 ** failed));
        }
      }
    })();
    return () => {
      stopped = true;
      controller.abort();
      kick.current();
    };
  }, [apply]);

  return { state, signedOut, offline, apply };
}

/** Compact listings while visible; the server answers 304 when nothing changed. */
export function useListings(
  floor: Floor,
  enabled: boolean,
  refreshKey: number,
) {
  const [parties, setParties] = useState<Listing[] | null>(null);
  const [failed, setFailed] = useState(false);
  const etags = useRef(
    new Map<Floor, { etag: string | null; parties: Listing[] }>(),
  );

  useEffect(() => {
    if (!enabled) return;
    const controller = new AbortController();
    const cached = etags.current.get(floor);
    setParties(cached ? cached.parties : null);
    const load = async () => {
      if (document.visibilityState === "hidden") return;
      try {
        const previous = etags.current.get(floor);
        const result = await partyApi.listings(
          floor,
          previous?.etag ?? null,
          controller.signal,
        );
        setFailed(false);
        if (result) {
          etags.current.set(floor, result);
          setParties(result.parties);
        }
      } catch {
        if (!controller.signal.aborted) setFailed(true);
      }
    };
    void load();
    const timer = setInterval(() => void load(), 20_000);
    const visible = () => void load();
    document.addEventListener("visibilitychange", visible);
    return () => {
      controller.abort();
      clearInterval(timer);
      document.removeEventListener("visibilitychange", visible);
    };
  }, [floor, enabled, refreshKey]);

  return { parties, failed };
}

/** Server-time countdown in whole seconds, ticking only while a deadline exists. */
export function useCountdown(deadline: number | null, serverTime: number) {
  const offset = useRef(0);
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    offset.current = serverTime * 1000 - Date.now();
  }, [serverTime]);
  useEffect(() => {
    if (deadline === null) return;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [deadline]);
  if (deadline === null) return null;
  return Math.max(0, Math.ceil(deadline - (now + offset.current) / 1000));
}
