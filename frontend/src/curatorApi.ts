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
    | { catalog: string; unchanged: true }
    | { catalog: string; items: CatalogItem[] }
  >(`/catalog${query}`);
  if ("unchanged" in response && cached) return cached.items;
  if (!("items" in response)) return getCatalogFresh();
  try {
    localStorage.setItem(
      CATALOG_KEY,
      JSON.stringify({ catalog: response.catalog, items: response.items }),
    );
  } catch {
    // Storage may be full or disabled; the list still works for this visit.
  }
  return response.items;
}

async function getCatalogFresh() {
  const response = await request<{ items: CatalogItem[] }>("/catalog");
  return response.items;
}

export function iconUrl(item: string) {
  return `${BASE}/icon/${encodeURIComponent(item)}.png`;
}
