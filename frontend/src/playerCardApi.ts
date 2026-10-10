export type FloorRecord = {
  floor: string;
  s_plus_ms: number | null;
  solo_clear_ms: number | null;
  ss_ms: number | null;
  terminals_ms: number | null;
};

export type PlayerCardData = {
  version: 1;
  user: { uuid: string; name: string };
  profile: { id: string; name: string } | null;
  catacombs: { level: number; experience: number } | null;
  secrets: number | null;
  magical_power: number | null;
  magical_power_basis: "highest_recorded";
  mod_records_available: boolean;
  floors: FloorRecord[];
  fetched_at: number;
};

function object(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
function numeric(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value) && value >= 0;
}
function nullableNumber(value: unknown) {
  return value === null || numeric(value);
}

export function parsePlayerCard(value: unknown, uuid: string): PlayerCardData {
  if (
    !object(value) ||
    value.version !== 1 ||
    !object(value.user) ||
    value.user.uuid !== uuid ||
    typeof value.user.name !== "string" ||
    !/^\w{1,16}$/.test(value.user.name) ||
    !(
      value.profile === null ||
      (object(value.profile) &&
        typeof value.profile.id === "string" &&
        /^[0-9a-f]{32}$/.test(value.profile.id) &&
        typeof value.profile.name === "string" &&
        value.profile.name.length <= 64)
    ) ||
    !(
      value.catacombs === null ||
      (object(value.catacombs) &&
        numeric(value.catacombs.level) &&
        numeric(value.catacombs.experience))
    ) ||
    !nullableNumber(value.secrets) ||
    !nullableNumber(value.magical_power) ||
    value.magical_power_basis !== "highest_recorded" ||
    typeof value.mod_records_available !== "boolean" ||
    !numeric(value.fetched_at) ||
    !Array.isArray(value.floors) ||
    value.floors.length !== 14
  ) {
    throw new Error("Unsupported player card");
  }
  const floors = new Set<string>();
  for (const row of value.floors) {
    if (
      !object(row) ||
      typeof row.floor !== "string" ||
      !/^[FM][1-7]$/.test(row.floor) ||
      floors.has(row.floor) ||
      ![row.s_plus_ms, row.solo_clear_ms, row.ss_ms, row.terminals_ms].every(
        nullableNumber,
      )
    ) {
      throw new Error("Unsupported player card");
    }
    floors.add(row.floor);
  }
  return value as PlayerCardData;
}

export async function getPlayerCard(
  uuid: string,
  signal: AbortSignal,
  partyMember = false,
): Promise<PlayerCardData> {
  const response = await fetch(
    partyMember
      ? `/api/v1/party/player-card/${encodeURIComponent(uuid)}`
      : "/api/v1/auth/player-card",
    {
      credentials: "same-origin",
      cache: "no-store",
      signal,
    },
  );
  if (response.status === 401)
    throw new Error("Your session ended. Sign in again.");
  if (!response.ok)
    throw new Error("Player stats are unavailable. Try again shortly.");
  return parsePlayerCard(await response.json(), uuid);
}

export function formatTime(millis: number | null | undefined) {
  if (millis == null) return "—";
  const total = Math.round(millis / 10);
  const minutes = Math.floor(total / 6000);
  const seconds = ((total % 6000) / 100).toFixed(2);
  return minutes ? `${minutes}m ${seconds}s` : `${seconds}s`;
}
