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

export type Standing = {
  rating: number;
  provisional: boolean;
  wins: number;
  losses: number;
  draws: number;
  peak: number | null;
};

export type Me = {
  version: 1;
  kind: "linked" | "guest";
  name: string | null;
  solo: SoloBest | null;
  rating?: Standing | null;
};

export type Inbox = {
  version: 1;
  revision: number;
  now: number;
  you: string;
  duel: string | null;
  incoming: { id: string; from: string; expires: number }[];
  outgoing: {
    id: string;
    kind: "challenge" | "invite";
    to: string | null;
    expires: number;
  }[];
};

export type DuelGuess = {
  score: number;
  distance: number | null;
  guessed: string | null;
  pin: [number, number] | null;
  health: number;
};

export type DuelRound = {
  round: number;
  multiplier: number;
  damage: number;
  lost: boolean | null;
  answer: RoundResult["answer"];
  captured_by: string | null;
  me: DuelGuess;
  opponent: DuelGuess;
};

export type RatingChange = {
  before: number;
  after: number;
  provisional: boolean;
};

export type Duel = {
  version: number;
  id: string;
  state: "loading" | "playing" | "revealed" | "finished";
  now: number;
  round: number;
  rounds: number;
  timer: number;
  health: number;
  multiplier: number;
  me: { name: string; health: number; guessed: boolean };
  opponent: {
    name: string;
    health: number;
    guessed: boolean;
    connected: boolean;
    guest: boolean;
  };
  results: DuelRound[];
  panorama?: string;
  countdown?: number;
  deadline?: number;
  next?: number;
  finished?: {
    result: "win" | "loss" | "draw";
    reason: "health" | "rounds" | "forfeit" | "cancelled";
    rating: RatingChange | null;
  };
};

export type Ranked = {
  rank: number;
  name: string;
  rating: number;
  wins: number;
  losses: number;
  draws: number;
  peak: number;
  you: boolean;
};

export type Leaderboard = {
  version: 1;
  season: string;
  players: number;
  top: Ranked[];
  you: Ranked | null;
  past: {
    season: string;
    top: { rank: number; name: string; rating: number }[];
  }[];
};

export type PastDuel = {
  id: string;
  finished: number;
  opponent: string;
  result: "win" | "loss" | "draw";
  reason: string;
  rated: boolean;
  rating: RatingChange | null;
  health: number;
  rounds: DuelRound[];
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

async function request<T>(
  path: string,
  body?: object,
  signal?: AbortSignal,
): Promise<T> {
  let response: Response;
  try {
    response = await fetch(BASE + path, {
      method: body ? "POST" : "GET",
      cache: "no-store",
      credentials: "same-origin",
      headers: body ? { "Content-Type": "application/json" } : undefined,
      body: body ? JSON.stringify({ version: 1, ...body }) : undefined,
      signal,
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

// Duels: the inbox and a duel's state are held requests that return when something changes.
export const getInbox = (after: number, signal?: AbortSignal) =>
  request<Inbox>(`/duels/inbox?after=${after}`, undefined, signal);
export const sendChallenge = (name: string) =>
  request<{ id: string; expires: number }>("/duels/challenge", { name });
export const createInvite = () =>
  request<{ code: string; expires: number }>("/duels/invite", {});
export const joinInvite = (code: string) =>
  request<{ duel: string }>("/duels/join", { code });
export const acceptChallenge = (id: string) =>
  request<{ duel: string }>(`/duels/challenges/${id}/accept`, {});
export const declineChallenge = (id: string) =>
  request<{ version: 1 }>(`/duels/challenges/${id}/decline`, {});
export const getDuel = (id: string, after: number, signal?: AbortSignal) =>
  request<Duel>(`/duels/${id}?after=${after}`, undefined, signal);
export const duelReady = (id: string, round: number) =>
  request<Duel>(`/duels/${id}/ready`, { round });
export const duelGuess = (id: string, round: number, x: number, z: number) =>
  request<Duel>(`/duels/${id}/guess`, { round, x, z });
export const leaveDuel = (id: string) =>
  request<{ version: 1 }>(`/duels/${id}/leave`, {});
export const rematch = (id: string) =>
  request<{ id: string; expires: number }>(`/duels/${id}/rematch`, {});
export const getLeaderboard = () => request<Leaderboard>("/leaderboard");
export const getHistory = () =>
  request<{ version: 1; total: number; duels: PastDuel[] }>("/duels/history");
