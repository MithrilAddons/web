import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { useEffect, useRef } from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { Duels } from "./LocationDuels";
import type { Duel, Me, World } from "./locationsApi";

vi.mock("./Panorama", () => ({
  Panorama: ({ src, onReady }: { src: string; onReady: () => void }) => {
    const ready = useRef(onReady);
    ready.current = onReady;
    useEffect(() => ready.current(), [src]);
    return <div data-testid="panorama" />;
  },
}));

const world: World = {
  version: 1,
  revision: "0123456789abcdef",
  x: -100,
  z: -50,
  width: 400,
  height: 200,
  islands: [
    { key: "hub", name: "Hub", box: [-100, -50, 200, 150] },
    { key: "fishing_1", name: "Backwater Bayou", box: [220, -50, 300, 30] },
  ],
  image: "/world.png",
};
const guest: Me = {
  version: 1,
  kind: "guest",
  name: "Guest #0042",
  solo: null,
  rating: null,
};
const linked: Me = {
  version: 1,
  kind: "linked",
  name: "Alice",
  solo: null,
  rating: {
    rating: 1532,
    provisional: true,
    wins: 1,
    losses: 0,
    draws: 0,
    peak: 1532,
  },
};
const ID = "d".repeat(22);
const now = () => Date.now() / 1000;
const answer = { island: "hub", name: "Hub", x: 10, z: 20 };

function duel(
  version: number,
  state: Duel["state"],
  extra: Partial<Duel> = {},
): Duel {
  return {
    version,
    id: ID,
    state,
    now: now(),
    round: 1,
    rounds: 6,
    timer: 25,
    health: 6000,
    multiplier: 1,
    me: { name: "Alice", health: 6000, guessed: false },
    opponent: {
      name: "Bob",
      health: 6000,
      guessed: false,
      connected: true,
      guest: false,
    },
    results: [],
    ...(state === "loading" || state === "playing"
      ? { panorama: "/round-1.webp" }
      : {}),
    ...(state === "playing" ? { deadline: now() + 20 } : {}),
    ...extra,
  };
}

const roundOne = {
  round: 1,
  multiplier: 1,
  damage: 1000,
  lost: false,
  answer,
  captured_by: "Jaminul",
  me: {
    score: 4500,
    distance: 12,
    guessed: "hub",
    pin: [22, 20] as [number, number],
    health: 6000,
  },
  opponent: {
    score: 3500,
    distance: 40,
    guessed: "hub",
    pin: [50, 20] as [number, number],
    health: 5000,
  },
};

type Reply = { status?: number; body: unknown } | "hold";

function serve(routes: Record<string, (init?: RequestInit) => Reply>) {
  const fetcher = vi.fn((url: string, init?: RequestInit) => {
    const path = url
      .replace("/api/v1/games/locations", "")
      .replace(ID, "ID")
      .split("?")[0]!;
    const query = new URLSearchParams(url.split("?")[1] ?? "");
    const route = routes[`${init?.method ?? "GET"} ${path}`];
    const ask = () =>
      route
        ? route({ ...init, headers: { after: query.get("after") ?? "" } })
        : "hold";
    const answer = (reply: Exclude<Reply, "hold">) =>
      new Response(JSON.stringify(reply.body), { status: reply.status ?? 200 });
    const first = ask();
    if (first !== "hold") return Promise.resolve(answer(first));
    // A held request answers once something changes, like the server's do.
    return new Promise<Response>((resolve, reject) => {
      const timer = setInterval(() => {
        const reply = ask();
        if (reply !== "hold") {
          clearInterval(timer);
          resolve(answer(reply));
        }
      }, 20);
      init?.signal?.addEventListener("abort", () => {
        clearInterval(timer);
        reject(new DOMException("aborted"));
      });
    });
  });
  vi.stubGlobal("fetch", fetcher);
  return fetcher;
}

function after(init?: RequestInit) {
  return Number((init?.headers as Record<string, string>).after);
}

function inbox(revision: number, extra = {}) {
  return {
    body: {
      version: 1,
      revision,
      now: now(),
      you: "Alice",
      duel: null,
      incoming: [],
      outgoing: [],
      ...extra,
    },
  };
}

beforeEach(() => {
  vi.stubGlobal(
    "ResizeObserver",
    class {
      observe() {}
      disconnect() {}
    },
  );
  for (const [name, value] of [
    ["clientWidth", 200],
    ["clientHeight", 200],
  ] as const)
    Object.defineProperty(HTMLElement.prototype, name, {
      configurable: true,
      get: () => value,
    });
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  window.history.replaceState(null, "", "/");
  for (const name of ["clientWidth", "clientHeight"])
    delete (HTMLElement.prototype as unknown as Record<string, unknown>)[name];
});

it("challenges by name, creates an invite and answers incoming challenges", async () => {
  const writeText = vi.fn(() => Promise.resolve());
  vi.stubGlobal("navigator", { clipboard: { writeText } });
  let revision = 0;
  let state = inbox(0);
  const fetcher = serve({
    "GET /duels/inbox": (init) => (after(init) >= revision ? "hold" : state),
    "POST /duels/challenge": () => {
      revision = 1;
      state = inbox(1, {
        outgoing: [
          {
            id: "c".repeat(12),
            kind: "challenge",
            to: "Bob",
            expires: now() + 120,
          },
        ],
      });
      return { body: { id: "c".repeat(12), expires: now() + 120 } };
    },
    "POST /duels/invite": () => ({
      body: { code: "ABC234", expires: now() + 600 },
    }),
    "POST /duels/challenges/cccccccccccc/decline": () => ({
      body: { version: 1 },
    }),
    "GET /duels/history": () => ({ body: { version: 1, total: 0, duels: [] } }),
  });
  render(<Duels world={world} me={guest} onChanged={vi.fn()} />);
  expect(await screen.findByText(/duels with guests are unrated/)).toBeTruthy();
  fireEvent.change(screen.getByLabelText("Minecraft name"), {
    target: { value: "Bob" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Challenge" }));
  expect(await screen.findByText(/Waiting for Bob to accept/)).toBeTruthy();
  const sent = fetcher.mock.calls.find(([url]) =>
    String(url).endsWith("/challenge"),
  );
  expect(JSON.parse(sent?.[1]?.body as string)).toEqual({
    version: 1,
    name: "Bob",
  });
  fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
  await waitFor(() =>
    expect(
      (
        screen.getByRole("button", {
          name: "Create invite link",
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(false),
  );
  fireEvent.click(screen.getByRole("button", { name: "Create invite link" }));
  expect(
    await screen.findByText(
      `${window.location.origin}/games/locations?join=ABC234`,
    ),
  ).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Copy link" }));
  expect(await screen.findByRole("button", { name: "Copied" })).toBeTruthy();
  expect(writeText).toHaveBeenCalledWith(
    `${window.location.origin}/games/locations?join=ABC234`,
  );
});

it("plays a duel from an accepted challenge to the result", async () => {
  let inboxRevision = 0;
  let inboxState = inbox(0, {
    incoming: [{ id: "i".repeat(12), from: "Bob", expires: now() + 100 }],
  });
  const states: Duel[] = [duel(1, "loading")];
  const onChanged = vi.fn();
  const fetcher = serve({
    "GET /duels/inbox": (init) =>
      after(init) >= inboxRevision ? "hold" : inboxState,
    "POST /duels/challenges/iiiiiiiiiiii/accept": () => {
      inboxRevision = 1;
      inboxState = inbox(1, { duel: ID });
      return { body: { duel: ID } };
    },
    "GET /duels/ID": (init) => {
      const next = states.find((item) => item.version > after(init));
      return next ? { body: next } : "hold";
    },
    "POST /duels/ID/ready": () => ({ body: duel(2, "playing") }),
    "POST /duels/ID/guess": () => {
      const revealed = duel(3, "revealed", {
        next: now() + 8,
        results: [roundOne],
        opponent: { ...duel(0, "loading").opponent, health: 5000 },
      });
      states.push(revealed);
      return { body: revealed };
    },
    "POST /duels/ID/rematch": () => ({
      body: { id: "r".repeat(12), expires: now() + 120 },
    }),
    "GET /duels/history": () => ({ body: { version: 1, total: 0, duels: [] } }),
  });
  render(<Duels world={world} me={linked} onChanged={onChanged} />);
  expect(await screen.findByText(/1532\?/)).toBeTruthy();
  fireEvent.click(await screen.findByRole("button", { name: "Accept" }));
  expect(await screen.findByText(/Round 1 of 6/)).toBeTruthy();
  const map = await screen.findByRole("img", { name: "Map of every island" });
  await screen.findByRole("button", {
    name: "Click the map to place your pin",
  });
  fireEvent.pointerDown(map.parentElement!, {
    clientX: 100,
    clientY: 100,
    pointerId: 1,
  });
  fireEvent.pointerUp(map.parentElement!, {
    clientX: 100,
    clientY: 100,
    pointerId: 1,
  });
  fireEvent.click(screen.getByRole("button", { name: "Guess" }));
  expect(await screen.findByText("Bob loses 1,000 health.")).toBeTruthy();
  expect(screen.getByText("12 blocks away.")).toBeTruthy();
  expect(screen.getByTitle("Bob's guess")).toBeTruthy();
  expect(screen.getByText(/Next round in/)).toBeTruthy();
  const guess = fetcher.mock.calls.find(([url]) =>
    String(url).endsWith("/guess"),
  );
  expect(JSON.parse(guess?.[1]?.body as string)).toEqual({
    version: 1,
    round: 1,
    x: 100,
    z: 50,
  });
  states.push(
    duel(4, "finished", {
      results: [roundOne],
      finished: {
        result: "win",
        reason: "health",
        rating: { before: 1500, after: 1532, provisional: true },
      },
    }),
  );
  // The held request picks the next version up on its own.
  states.push(
    duel(5, "finished", {
      results: [roundOne],
      finished: states.at(-1)!.finished,
    }),
  );
  await waitFor(() => expect(screen.queryByText("You won!")).toBeTruthy(), {
    timeout: 3000,
  });
  expect(screen.getByText("Bob ran out of health.")).toBeTruthy();
  expect(screen.getByText(/Rating 1500 → 1532\? \(\+32\)/)).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Rematch" }));
  expect(
    await screen.findByRole("button", { name: "Waiting for Bob…" }),
  ).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Back to duels" }));
  expect(onChanged).toHaveBeenCalled();
  expect(await screen.findByText("Challenge a player")).toBeTruthy();
});

it("joins from an invite link and forfeits", async () => {
  window.history.replaceState(null, "", "/games/locations?join=abc234");
  let duelReady = false;
  serve({
    "GET /duels/inbox": (init) => (after(init) >= 0 ? "hold" : inbox(0)),
    "POST /duels/join": () => {
      duelReady = true;
      return { body: { duel: ID } };
    },
    "GET /duels/ID": (init) => {
      if (!duelReady) return "hold";
      if (after(init) < 1)
        return {
          body: duel(1, "loading", {
            countdown: now() + 3,
            opponent: {
              name: "Guest #0007",
              health: 6000,
              guessed: false,
              connected: false,
              guest: true,
            },
          }),
        };
      return "hold";
    },
    "POST /duels/ID/ready": () => "hold",
    "POST /duels/ID/leave": () => ({ body: { version: 1 } }),
  });
  render(<Duels world={world} me={guest} onChanged={vi.fn()} />);
  fireEvent.click(
    await screen.findByRole("button", { name: "Join duel ABC234" }),
  );
  expect(await screen.findByText("Get ready…")).toBeTruthy();
  expect(screen.getByText(/reconnecting…/)).toBeTruthy();
  expect(screen.getByText(/Starting in/)).toBeTruthy();
  expect(window.location.search).toBe("");
  fireEvent.click(screen.getByRole("button", { name: "Forfeit" }));
});

it("goes back to the lobby when the duel has ended, and shows a linked player's history", async () => {
  serve({
    "GET /duels/inbox": (init) =>
      after(init) >= 0 ? "hold" : inbox(0, { duel: ID }),
    "GET /duels/ID": () => ({
      status: 404,
      body: { detail: "This duel has ended" },
    }),
    "GET /duels/history": () => ({
      body: {
        version: 1,
        total: 2,
        duels: [
          {
            id: "a".repeat(22),
            finished: now(),
            opponent: "Bob",
            result: "win",
            reason: "health",
            rated: true,
            rating: { before: 1500, after: 1532, provisional: true },
            health: 4000,
            rounds: [],
          },
          {
            id: "b".repeat(22),
            finished: now(),
            opponent: "Guest #0007",
            result: "draw",
            reason: "rounds",
            rated: false,
            rating: null,
            health: 6000,
            rounds: [],
          },
        ],
      },
    }),
  });
  render(
    <Duels
      world={world}
      me={{ ...linked, rating: null }}
      onChanged={vi.fn()}
    />,
  );
  expect(await screen.findByText("Won against Bob")).toBeTruthy();
  expect(screen.getByText("+32")).toBeTruthy();
  expect(screen.getByText("Drew against Guest #0007")).toBeTruthy();
  expect(screen.getByText("unrated")).toBeTruthy();
  expect(screen.getByText(/Everyone starts at 1500/)).toBeTruthy();
  expect(await screen.findByText("Challenge a player")).toBeTruthy();
});

it("reports errors from the lobby", async () => {
  serve({
    "GET /duels/inbox": (init) => (after(init) >= 0 ? "hold" : inbox(0)),
    "POST /duels/challenge": () => ({
      status: 404,
      body: { detail: "Bob doesn't have the game open right now" },
    }),
  });
  render(<Duels world={world} me={null} onChanged={vi.fn()} />);
  fireEvent.change(screen.getByLabelText("Minecraft name"), {
    target: { value: "Bob" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Challenge" }));
  expect(await screen.findByRole("alert")).toHaveProperty(
    "textContent",
    "Bob doesn't have the game open right now",
  );
});
