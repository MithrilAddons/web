/** Curator cell text, hints, search and sharing; matches the MithrilPF mod's wording. */

export type Match = "exact" | "partial" | "none";
export type Arrow = "up" | "down";
export type Feedback = { match: Match; arrow?: Arrow };

export type Values = {
  rarity: string | null;
  type: string | null;
  museum: string | null;
  stage: string | null;
  requirements: Record<string, number | null>;
  soulbound: string | null;
  origin: string | null;
  market: number | null;
  npc: number | null;
  length: number;
};

export type Guess = {
  item: string;
  name: string;
  values: Values;
  feedback: Record<Column, Feedback>;
  family: boolean;
};

export type Column = keyof Values;

export type ColumnInfo = {
  key: Column;
  name: string;
  label: string;
  short: string;
  help: string;
};

export const COLUMNS: readonly ColumnInfo[] = [
  {
    key: "rarity",
    name: "Rarity",
    label: "Rarity",
    short: "Rar.",
    help: "How rare the item is",
  },
  {
    key: "type",
    name: "Type",
    label: "Type",
    short: "Type",
    help: "The item's category, like sword or necklace",
  },
  {
    key: "museum",
    name: "Museum",
    label: "Museum",
    short: "Mus.",
    help: "The museum category, Special, or not in the museum",
  },
  {
    key: "stage",
    name: "Game stage",
    label: "Stage",
    short: "Stg.",
    help: "The museum's game stage, from Starter to Master",
  },
  {
    key: "requirements",
    name: "Requirements",
    label: "Req.",
    short: "Req.",
    help: "Skill, Catacombs, slayer and other levels needed to use it",
  },
  {
    key: "soulbound",
    name: "Soulbound",
    label: "Soulb.",
    short: "Soul",
    help: "Whether it starts soulbound to a player or a co-op",
  },
  {
    key: "origin",
    name: "Origin",
    label: "Origin",
    short: "Orig",
    help: "Where the item comes from, such as the Rift",
  },
  {
    key: "market",
    name: "Market value",
    label: "Market",
    short: "Mkt",
    help: "Lowest BIN or Bazaar price at 00:00 UTC; green within 10%",
  },
  {
    key: "npc",
    name: "NPC sell price",
    label: "NPC",
    short: "NPC",
    help: "What an NPC pays for it; green within 10%",
  },
  {
    key: "length",
    name: "Length",
    label: "Length",
    short: "Len",
    help: "Characters in the full name, spaces included",
  },
];

const RARITY: Record<string, string> = {
  COMMON: "COM",
  UNCOMMON: "UNC",
  RARE: "RARE",
  EPIC: "EPIC",
  LEGENDARY: "LEG",
  MYTHIC: "MYTH",
  DIVINE: "DIV",
  SUPREME: "DIV",
  SPECIAL: "SPEC",
  VERY_SPECIAL: "VSPEC",
};
const RARITY_ORDER = [
  "COMMON",
  "UNCOMMON",
  "RARE",
  "EPIC",
  "LEGENDARY",
  "MYTHIC",
  "DIVINE",
  "SPECIAL",
  "VERY_SPECIAL",
];
const TYPE: Record<string, string> = {
  ACCESSORY: "Acc.",
  NECKLACE: "Neck.",
  SWORD: "Sword",
  LONGSWORD: "Long",
  HELMET: "Helm.",
  CHESTPLATE: "Chest",
  LEGGINGS: "Legs",
  BOOTS: "Boots",
  BRACELET: "Brace.",
  GLOVES: "Gloves",
  FARMING_TOOL: "Farm",
  FISHING_ROD: "Rod",
  PICKAXE: "Pick",
  REFORGE_STONE: "Stone",
  PET_ITEM: "Pet",
};
const MUSEUM: Record<string, string> = {
  COMBAT: "Combat",
  DUNGEONEERING: "Dung.",
  FARMING: "Farm.",
  FISHING: "Fish.",
  MINING: "Mining",
  FORAGING: "Forag.",
  HUNTING: "Hunt.",
  SPECIAL: "Special",
};
const STAGE: Record<string, string> = {
  STARTER: "Start",
  AMATEUR: "Amat.",
  INTERMEDIATE: "Inter.",
  SKILLED: "Skill.",
  EXPERT: "Exp.",
  PROFESSIONAL: "Pro.",
  MASTER: "Mast.",
};
const STAGE_ORDER = Object.keys(STAGE);
const SKILL: Record<string, string> = {
  COMBAT: "Cmb",
  MINING: "Min",
  FARMING: "Frm",
  FISHING: "Fsh",
  FORAGING: "For",
  ENCHANTING: "Ench",
  ALCHEMY: "Alch",
  TAMING: "Tam",
  CARPENTRY: "Carp",
  RUNECRAFTING: "Rune",
  SOCIAL: "Soc",
  HUNTING: "Hnt",
};
const SLAYER: Record<string, string> = {
  ZOMBIE: "Rev",
  SPIDER: "Tara",
  WOLF: "Sven",
  ENDERMAN: "Eman",
  BLAZE: "Blaze",
  VAMPIRE: "Vamp",
};
const PRIORITY = [
  "SKILL",
  "DUNGEON_SKILL",
  "DUNGEON_TIER",
  "SLAYER",
  "HEART_OF_THE_MOUNTAIN",
];

/** SkyBlock's own rarity colours, so the answer reads as it does in game. */
export const RARITY_COLOUR: Record<string, string> = {
  UNCOMMON: "#55ff55",
  RARE: "#5555ff",
  EPIC: "#aa00aa",
  LEGENDARY: "#ffaa00",
  MYTHIC: "#ff55ff",
  DIVINE: "#55ffff",
  SUPREME: "#55ffff",
  SPECIAL: "#ff5555",
  VERY_SPECIAL: "#ff5555",
};

export function words(value: string) {
  return value
    .split("_")
    .filter(Boolean)
    .map((part) => part.charAt(0) + part.slice(1).toLowerCase())
    .join(" ");
}

function pick(map: Record<string, string>, value: string | null) {
  if (value === null) return "—";
  return map[value] ?? words(value).slice(0, 6);
}

/** "1.2M", "140k", "17.4k": one decimal below a hundred of a unit. */
export function amount(value: number) {
  const size = Math.abs(value);
  const unit = (
    [
      [1e9, "B"],
      [1e6, "M"],
      [1e3, "k"],
    ] as const
  ).find(([step]) => size >= step);
  const scaled = unit ? value / unit[0] : value;
  const suffix = unit ? unit[1] : "";
  const short =
    (Math.abs(scaled) < 100 && suffix) || Math.abs(scaled) < 10
      ? scaled.toFixed(1).replace(/\.0$/, "")
      : scaled.toFixed(0);
  return short + suffix;
}

function number(value: number) {
  return Number.isInteger(value)
    ? value.toLocaleString("en-US")
    : value.toLocaleString("en-US", {
        minimumFractionDigits: 1,
        maximumFractionDigits: 1,
      });
}

function kindOf(key: string) {
  const split = key.indexOf(":");
  return split < 0 ? [key, ""] : [key.slice(0, split), key.slice(split + 1)];
}

function requirementShort(key: string) {
  const [kind = "", qualifier = ""] = kindOf(key);
  switch (kind) {
    case "SKILL":
      return SKILL[qualifier] ?? words(qualifier).slice(0, 4);
    case "DUNGEON_SKILL":
      return "Cata";
    case "DUNGEON_TIER":
      return "Floor";
    case "SLAYER":
      return SLAYER[qualifier] ?? "Slay";
    case "HEART_OF_THE_MOUNTAIN":
      return "HotM";
    case "GARDEN_LEVEL":
      return "Gdn";
    case "COLLECTION":
      return "Coll";
    case "CRIMSON_ISLE_REPUTATION":
      return "Rep";
    case "KUUDRA_COMPLETION":
      return "Kuudra";
    default:
      return (words(kind).split(" ")[0] ?? "").slice(0, 5);
  }
}

function requirementName(key: string) {
  const [kind = "", qualifier = ""] = kindOf(key);
  switch (kind) {
    case "SKILL":
      return words(qualifier);
    case "DUNGEON_SKILL":
      return "Catacombs";
    case "DUNGEON_TIER":
      return "Floor";
    case "SLAYER":
      return `${words(qualifier)} Slayer`;
    case "HEART_OF_THE_MOUNTAIN":
      return "HotM";
    default:
      return [words(kind), words(qualifier)].filter(Boolean).join(" ");
  }
}

function priority(key: string) {
  const index = PRIORITY.indexOf(kindOf(key)[0] ?? "");
  return index < 0 ? PRIORITY.length : index;
}

function requirement(requirements: Record<string, number | null>) {
  const keys = Object.keys(requirements);
  const key = keys.reduce<string | undefined>(
    (best, next) =>
      best === undefined || priority(next) < priority(best) ? next : best,
    undefined,
  );
  if (key === undefined) return "—";
  const level = requirements[key];
  const more = keys.length > 1 ? "+" : "";
  const short = requirementShort(key);
  return level === null || level === undefined
    ? short + more
    : `${short} ${level}${more}`;
}

/** The short value shown in a grid cell. */
export function cell(column: Column, values: Values): string {
  switch (column) {
    case "rarity":
      return pick(RARITY, values.rarity);
    case "type":
      return pick(TYPE, values.type);
    case "museum":
      return pick(MUSEUM, values.museum);
    case "stage":
      return pick(STAGE, values.stage);
    case "requirements":
      return requirement(values.requirements);
    case "soulbound":
      if (values.soulbound === null) return "No";
      return values.soulbound === "COOP" ? "Co-op" : words(values.soulbound);
    case "origin":
      return values.origin === null ? "—" : words(values.origin);
    case "market":
      return values.market === null ? "—" : amount(values.market);
    case "npc":
      return values.npc === null ? "—" : amount(values.npc);
    case "length":
      return String(values.length);
  }
}

/** The value in full, for tooltips. */
export function full(column: Column, values: Values): string {
  switch (column) {
    case "requirements":
      return (
        Object.entries(values.requirements)
          .map(([key, level]) =>
            [requirementName(key), level === null ? null : number(level)]
              .filter(Boolean)
              .join(" "),
          )
          .join(", ") || "None"
      );
    case "soulbound":
      if (values.soulbound === null) return "No";
      return values.soulbound === "COOP" ? "Co-op" : words(values.soulbound);
    case "market":
      return values.market === null ? "Not tradeable" : number(values.market);
    case "npc":
      return values.npc === null ? "None" : number(values.npc);
    case "length":
      return String(values.length);
    case "museum":
      return values.museum === null ? "Not in museum" : words(values.museum);
    default:
      return values[column] === null ? "None" : words(values[column]);
  }
}

export function arrowText(feedback: Feedback) {
  if (feedback.arrow === "up") return "↑";
  return feedback.arrow === "down" ? "↓" : "";
}

const UP: Partial<Record<Column, string>> = {
  rarity: "The answer is rarer",
  stage: "The answer belongs to a later stage",
  requirements: "The answer needs a higher level",
  market: "The answer is worth more",
  npc: "NPCs pay more for the answer",
  length: "The answer's name is longer",
};
const DOWN: Partial<Record<Column, string>> = {
  rarity: "The answer is less rare",
  stage: "The answer belongs to an earlier stage",
  requirements: "The answer needs a lower level",
  market: "The answer is worth less",
  npc: "NPCs pay less for the answer",
  length: "The answer's name is shorter",
};

/** What a cell's colour and arrow say about the answer. */
export function hint(column: Column, feedback: Feedback) {
  if (feedback.arrow === "up") return UP[column] ?? "";
  if (feedback.arrow === "down") return DOWN[column] ?? "";
  if (feedback.match === "exact") return "Matches the answer";
  if (feedback.match === "partial") {
    return column === "soulbound"
      ? "Both soulbound, but not the same way"
      : "Some requirements match the answer's";
  }
  return "Doesn't match the answer";
}

export type CatalogItem = readonly [id: string, name: string];

/** Up to `limit` names starting with the text, then names with a word starting with it. */
export function suggestions(
  items: readonly CatalogItem[],
  query: string,
  guessed: ReadonlySet<string>,
  limit = 8,
): CatalogItem[] {
  const needle = query.trim().toLowerCase();
  if (!needle) return [];
  const ranked: [number, CatalogItem][] = [];
  for (const item of items) {
    if (guessed.has(item[0])) continue;
    const name = item[1].toLowerCase();
    if (name.startsWith(needle)) ranked.push([0, item]);
    else if (name.split(/[ \-'(]/).some((word) => word.startsWith(needle)))
      ranked.push([1, item]);
  }
  ranked.sort(
    (a, b) =>
      a[0] - b[0] ||
      a[1][1].length - b[1][1].length ||
      ordinal(a[1][1], b[1][1]),
  );
  return ranked.slice(0, limit).map(([, item]) => item);
}

/** Plain code-unit order, as the mod sorts names. */
function ordinal(a: string, b: string) {
  if (a < b) return -1;
  return a > b ? 1 : 0;
}

/** The item whose whole name matches, ignoring case. */
export function exact(items: readonly CatalogItem[], query: string) {
  const needle = query.trim().toLowerCase();
  return items.find((item) => item[1].toLowerCase() === needle);
}

/** The Discord-friendly squares the mod copies too. */
export function share(
  number: number,
  guesses: readonly Guess[],
  solved: boolean,
  limit: number,
) {
  const square: Record<Match, string> = {
    exact: "🟩",
    partial: "🟨",
    none: "⬛",
  };
  return [
    `Curator #${number} ${solved ? guesses.length : "X"}/${limit}`,
    ...guesses.map((guess) =>
      COLUMNS.map(({ key }) => square[guess.feedback[key].match]).join(""),
    ),
  ].join("\n");
}

export type Known = { text: string; state: Match | "range" | "unknown" };

function bounds(
  guesses: readonly Guess[],
  column: Column,
  value: (values: Values) => number | null,
) {
  let low: number | undefined;
  let high: number | undefined;
  for (const guess of guesses) {
    const seen = value(guess.values);
    const arrow = guess.feedback[column].arrow;
    if (seen === null || arrow === undefined) continue;
    if (arrow === "up") low = low === undefined ? seen : Math.max(low, seen);
    else high = high === undefined ? seen : Math.min(high, seen);
  }
  return [low, high] as const;
}

function ranked(order: string[], value: string | null) {
  if (value === null) return null;
  const index = order.indexOf(value === "SUPREME" ? "DIVINE" : value);
  return index < 0 ? null : index;
}

function range(low: string | undefined, high: string | undefined) {
  if (low !== undefined && high !== undefined) return `${low} – ${high}`;
  if (low !== undefined) return `over ${low}`;
  return high === undefined ? "" : `under ${high}`;
}

/** Everything learned so far about one clue, from every guess. */
export function known(guesses: readonly Guess[], column: Column): Known {
  const hit = guesses.find((guess) => guess.feedback[column].match === "exact");
  if (hit) {
    const values = hit.values;
    const text =
      column === "market" || column === "npc"
        ? cell(column, values)
        : full(column, values);
    return { text, state: "exact" };
  }
  let text = "";
  if (column === "market" || column === "npc" || column === "length") {
    const [low, high] = bounds(guesses, column, (values) => values[column]);
    const format = column === "length" ? String : amount;
    const show = (value: number | undefined) =>
      value === undefined ? undefined : format(value);
    text = range(show(low), show(high));
  } else if (column === "rarity" || column === "stage") {
    const order = column === "rarity" ? RARITY_ORDER : STAGE_ORDER;
    const [low, high] = bounds(guesses, column, (values) =>
      ranked(order, values[column]),
    );
    text = [
      low === undefined ? "" : `above ${words(order[low] ?? "")}`,
      high === undefined ? "" : `below ${words(order[high] ?? "")}`,
    ]
      .filter(Boolean)
      .join(", ");
  }
  if (text) return { text, state: "range" };
  const partial = [...guesses]
    .reverse()
    .find((guess) => guess.feedback[column].match === "partial");
  if (partial) return { text: cell(column, partial.values), state: "partial" };
  return { text: "—", state: "unknown" };
}

/** "3h 12m" until the next item, never below a minute. */
export function countdown(milliseconds: number) {
  const minutes = Math.max(1, Math.ceil(milliseconds / 60_000));
  const hours = Math.floor(minutes / 60);
  return hours > 0 ? `${hours}h ${minutes % 60}m` : `${minutes}m`;
}
