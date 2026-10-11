export type Island = {
  key: string;
  name: string;
  box: [number, number, number, number];
};

export type World = {
  version: 1;
  revision: string;
  x: number;
  z: number;
  width: number;
  height: number;
  islands: Island[];
  image: string;
};

export type RoundResult = {
  score: number;
  distance: number | null;
  guessed: string | null;
  pin: [number, number] | null;
  answer: { island: string; name: string; x: number; z: number };
  captured_by: string | null;
};

export type SoloBest = {
  best: number | null;
  runs: number;
  average: number | null;
};

export type Run = {
  version: 1;
  id: string;
  round: number;
  rounds: number;
  timer: number;
  state: "loading" | "playing" | "revealed" | "finished";
  now: number;
  results: RoundResult[];
  total: number;
  panorama?: string;
  deadline?: number;
  best?: SoloBest & { new_best: boolean };
};

export type Me = {
  version: 1;
  kind: "linked" | "guest";
  name: string | null;
  solo: SoloBest | null;
};

export class LocationsError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

const BASE = "/api/v1/games/locations";

async function request<T>(path: string, body?: object): Promise<T> {
  let response: Response;
  try {
    response = await fetch(BASE + path, {
      method: body ? "POST" : "GET",
      cache: "no-store",
      credentials: "same-origin",
      headers: body ? { "Content-Type": "application/json" } : undefined,
      body: body ? JSON.stringify({ version: 1, ...body }) : undefined,
    });
  } catch {
    throw new LocationsError(0, "Can't reach Mithril. Check your connection.");
  }
  if (!response.ok) {
    let detail = "Something went wrong. Try again.";
    try {
      const value: unknown = await response.json();
      if (
        typeof value === "object" &&
        value !== null &&
        "detail" in value &&
        typeof value.detail === "string"
      )
        detail = value.detail;
    } catch {
      // Keep the generic message for a body that isn't JSON.
    }
    throw new LocationsError(response.status, detail);
  }
  return (await response.json()) as T;
}

export const getWorld = () => request<World>("/world");
export const getMe = () => request<Me>("/me");
export const startSolo = () => request<Run>("/solo", {});
export const getSolo = (id: string) => request<Run>(`/solo/${id}`);
export const sendReady = (id: string, round: number) =>
  request<Run>(`/solo/${id}/ready`, { round });
export const sendGuess = (id: string, round: number, x: number, z: number) =>
  request<Run>(`/solo/${id}/guess`, { round, x, z });
export const sendNext = (id: string, round: number) =>
  request<Run>(`/solo/${id}/next`, { round });
