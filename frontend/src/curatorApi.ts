import type { CatalogItem, Guess, Values } from "./curatorFormat";

export type Today =
  | { version: 1; day: string; state: "preparing"; resets_at: number }
  | {
      version: 1;
      day: string;
      number: number;
      state: "playing" | "solved" | "failed";
      limit: number;
      resets_at: number;
      guesses: Guess[];
      answer?: { item: string; name: string; values: Values };
      stats?: {
        played: number;
        solved: number;
        streak: number;
        best_streak: number;
      };
    };

export type Standing = {
  rank: number;
  name: string;
  points: number;
  solved: number;
  played: number;
  streak: number;
  you: boolean;
};

export type Leaderboard = {
  version: 1;
  season: string;
  day: number;
  days: number;
  players: number;
  top: Standing[];
  you: Standing | null;
  stats: {
    points: number;
    rank: number | null;
    played: number;
    solved: number;
    average: number | null;
    histogram: number[];
    failed: number;
    streak: number;
    best_streak: number;
  } | null;
};

export class CuratorError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

const BASE = "/api/v1/games/curator";
const CATALOG_KEY = "mithril.curator.catalog";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(BASE + path, {
      cache: "no-store",
      credentials: "same-origin",
      ...init,
    });
  } catch {
    throw new CuratorError(
      0,
      "Can't reach Mithril. Your guesses so far are saved.",
    );
  }
  if (!response.ok) {
    let detail = "Something went wrong. Try again.";
    try {
      const body: unknown = await response.json();
      if (
        typeof body === "object" &&
        body !== null &&
        "detail" in body &&
        typeof body.detail === "string"
      )
        detail = body.detail;
    } catch {
      // Keep the generic message for a body that isn't JSON.
    }
    throw new CuratorError(response.status, detail);
  }
  return (await response.json()) as T;
}

export function getToday() {
  return request<Today>("/today");
}

export function sendGuess(day: string, item: string) {
  return request<Today>("/guess", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ version: 1, day, item }),
  });
}

const GUEST_KEY = "mithril.curator.guest";

type GuestRound = { day: string; items: string[] };

function storedGuest(): GuestRound | null {
  try {
    const value: unknown = JSON.parse(
      localStorage.getItem(GUEST_KEY) ?? "null",
    );
    if (
      typeof value === "object" &&
      value !== null &&
      "day" in value &&
      typeof value.day === "string" &&
      "items" in value &&
      Array.isArray(value.items) &&
      value.items.every((item) => typeof item === "string")
    )
      return value as GuestRound;
  } catch {
    // A damaged or blocked store just starts today's round again.
  }
  return null;
}

function storeGuest(round: GuestRound | null) {
  try {
    if (round) localStorage.setItem(GUEST_KEY, JSON.stringify(round));
    else localStorage.removeItem(GUEST_KEY);
  } catch {
    // The guesses still count for this visit.
  }
}

/** A guest round is judged on the server but remembered only by this browser. */
async function playAsGuest(day: string | null, items: string[]) {
  const today = await request<Today>("/guest", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ version: 1, day, items }),
  });
  if (today.state !== "preparing")
    storeGuest({ day: today.day, items: today.guesses.map((g) => g.item) });
  return today;
}

export async function getGuestToday() {
  const saved = storedGuest();
  if (!saved?.items.length) return playAsGuest(null, []);
  try {
    return await playAsGuest(saved.day, saved.items);
  } catch (error) {
    // Yesterday's guesses, or ones the server no longer accepts: start today afresh.
    if (
      !(error instanceof CuratorError) ||
      ![404, 409, 422].includes(error.status)
    )
      throw error;
    storeGuest(null);
    return playAsGuest(null, []);
  }
}

export function sendGuestGuess(
  today: { day: string; guesses: Guess[] },
  item: string,
) {
  return playAsGuest(today.day, [...today.guesses.map((g) => g.item), item]);
}

export function getLeaderboard() {
  return request<Leaderboard>("/leaderboard");
}

type Catalog = { catalog: string; items: CatalogItem[] };

function cachedCatalog(): Catalog | null {
  try {
    const value: unknown = JSON.parse(
      localStorage.getItem(CATALOG_KEY) ?? "null",
    );
    if (
      typeof value === "object" &&
      value !== null &&
      "catalog" in value &&
      typeof value.catalog === "string" &&
      "items" in value &&
      Array.isArray(value.items)
    )
      return value as Catalog;
  } catch {
    // A damaged or blocked cache just means downloading the list again.
  }
  return null;
}

/** The guessable item names, kept in the browser until the catalog changes. */
export async function getCatalog(): Promise<CatalogItem[]> {
  const cached = cachedCatalog();
  const query = cached ? `?version=${encodeURIComponent(cached.catalog)}` : "";
  const response = await request<
    { catalog: string; unchanged: true } | CatalogResponse
  >(`/catalog${query}`);
  if ("unchanged" in response && cached) return cached.items;
  if (!("items" in response)) return withRarities(await request("/catalog"));
  const items = withRarities(response);
  try {
    localStorage.setItem(
      CATALOG_KEY,
      JSON.stringify({ catalog: response.catalog, items }),
    );
  } catch {
    // Storage may be full or disabled; the list still works for this visit.
  }
  return items;
}

type CatalogResponse = {
  catalog: string;
  items: [string, string][];
  rarities?: (string | null)[];
};

/** Each item with its rarity, which the API sends beside the [id, name] pairs. */
function withRarities(response: CatalogResponse): CatalogItem[] {
  return response.items.map(([id, name], index) => [
    id,
    name,
    response.rarities?.[index] ?? null,
  ]);
}

export function iconUrl(item: string) {
  return `${BASE}/icon/${encodeURIComponent(item)}.png`;
}
