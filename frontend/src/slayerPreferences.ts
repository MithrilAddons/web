import { eligible, slayers, type Slayer } from "./slayerCalculator";

const prefix = "mithril.slayer-profits.v1:";
const toggles = [
  "boost",
  "shards",
  "aatroxXp",
  "halfPrice",
  "extraSlots",
  "petXpBoost",
  "excludeActive",
] as const;

export function defaultSlayerSettings(slayer: Slayer) {
  return {
    tierNumber: Math.max(...slayer.tiers.map((tier) => tier.number)),
    magicFind: "200",
    bosses: "60",
    meter: "",
    boost: false,
    shards: false,
    aatroxXp: false,
    halfPrice: false,
    extraSlots: false,
    petXpBoost: false,
    excludeActive: false,
    mode: "instant" as "instant" | "offer",
  };
}
export type SlayerSettings = ReturnType<typeof defaultSlayerSettings>;

function validInput(value: unknown, max: number): value is string {
  return (
    typeof value === "string" &&
    value.trim() !== "" &&
    Number.isFinite(+value) &&
    +value >= 0 &&
    +value <= max
  );
}

export function loadSlayerSettings(slayer: Slayer): SlayerSettings {
  const settings = defaultSlayerSettings(slayer);
  try {
    const stored: unknown = JSON.parse(
      localStorage.getItem(prefix + slayer.displayName) ?? "null",
    );
    if (!stored || typeof stored !== "object" || Array.isArray(stored))
      return settings;
    const value = stored as Record<string, unknown>;
    const tier =
      slayer.tiers.find((tier) => tier.number === value.tierNumber) ??
      slayer.tiers.find((tier) => tier.number === settings.tierNumber)!;
    settings.tierNumber = tier.number;
    if (validInput(value.magicFind, 10000))
      settings.magicFind = value.magicFind;
    if (validInput(value.bosses, 100000)) settings.bosses = value.bosses;
    if (
      tier.number >= 3 &&
      tier.drops.some((drop) => eligible(drop) && drop.name === value.meter)
    )
      settings.meter = value.meter as string;
    if (value.mode === "offer") settings.mode = "offer";
    for (const key of toggles)
      if (typeof value[key] === "boolean") settings[key] = value[key];
  } catch {
    /* Browser storage may be unavailable or contain invalid data. */
  }
  return settings;
}

export function saveSlayerSettings(slayer: Slayer, settings: SlayerSettings) {
  if (
    !validInput(settings.magicFind, 10000) ||
    !validInput(settings.bosses, 100000)
  )
    return;
  try {
    localStorage.setItem(prefix + slayer.displayName, JSON.stringify(settings));
  } catch {
    /* Keep the calculator usable when browser storage is unavailable. */
  }
}

export function loadSelectedSlayer(): number {
  try {
    const name = localStorage.getItem(prefix + "selected");
    return Math.max(
      0,
      slayers.findIndex((slayer) => slayer.displayName === name),
    );
  } catch {
    return 0;
  }
}

export function saveSelectedSlayer(slayer: Slayer) {
  try {
    localStorage.setItem(prefix + "selected", slayer.displayName);
  } catch {
    /* Selection still works without browser storage. */
  }
}
