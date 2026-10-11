import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { useEffect, useRef } from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { Locations } from "./Locations";

vi.mock("./Panorama", () => ({
  Panorama: ({ src, onReady }: { src: string; onReady: () => void }) => {
    // Ready once per image, like the real viewer.
    const ready = useRef(onReady);
    ready.current = onReady;
    useEffect(() => ready.current(), [src]);
    return <div data-testid="panorama" data-src={src} />;
  },
}));

const world = {
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

const now = () => Date.now() / 1000;
const answer = { island: "hub", name: "Hub", x: 10, z: 20 };
const result = (score: number, extra = {}) => ({
  score,
  distance: 12,
  guessed: "hub",
  pin: [22, 20],
  answer,
  captured_by: "Jaminul",
  ...extra,
});

function run(round: number, state: string, results: unknown[], extra = {}) {
  return {
    version: 1,
    id: "r".repeat(22),
    round,
    rounds: 5,
    timer: 25,
    state,
    now: now(),
    results,
    total: results.reduce(
      (sum: number, item) => sum + (item as { score: number }).score,
      0,
    ),
    ...(state === "loading" || state === "playing"
      ? {
          panorama: `/api/v1/games/locations/panorama/${"t".repeat(23)}${round}.webp`,
        }
      : {}),
    ...(state === "playing" ? { deadline: now() + 20 } : {}),
    ...extra,
  };
}

type Reply = { status?: number; body: unknown };
function serve(
  routes: Record<string, Reply | ((init?: RequestInit) => Reply)>,
) {
  const fetcher = vi.fn((url: string, init?: RequestInit) => {
    const path = url
      .replace("/api/v1/games/locations", "")
      .replace(/r{22}/, "ID");
    const route = routes[`${init?.method ?? "GET"} ${path}`];
    const reply = typeof route === "function" ? route(init) : route;
    if (!reply) return Promise.reject(new TypeError("offline"));
    return Promise.resolve(
      new Response(JSON.stringify(reply.body), { status: reply.status ?? 200 }),
    );
  });
  vi.stubGlobal("fetch", fetcher);
  return fetcher;
}

beforeEach(() => {
  localStorage.clear();
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
  localStorage.clear();
  for (const name of ["clientWidth", "clientHeight"])
    delete (HTMLElement.prototype as unknown as Record<string, unknown>)[name];
});

function clickMap() {
  const map = screen.getByRole("img", {
    name: "Map of every island",
  }).parentElement!;
  fireEvent.pointerDown(map, { clientX: 100, clientY: 100, pointerId: 1 });
  fireEvent.pointerUp(map, { clientX: 100, clientY: 100, pointerId: 1 });
}

it("plays a guest's solo run and keeps the best in the browser", async () => {
  const guest = { version: 1, kind: "guest", name: "Guest #0042", solo: null };
  let round = 1;
  const done: unknown[] = [];
  const fetcher = serve({
    "GET /world": { body: world },
    "GET /me": { body: guest },
    "POST /solo": () => {
      round = 1;
      done.length = 0;
      return { body: run(1, "loading", []) };
    },
    "POST /solo/ID/ready": () => ({ body: run(round, "playing", [...done]) }),
    "POST /solo/ID/guess": () => {
      done.push(
        result(
          round === 2 ? 0 : 4000,
          round === 2 ? { distance: null, guessed: "fishing_1" } : {},
        ),
      );
      return {
        body: run(round, round === 5 ? "finished" : "revealed", [...done]),
      };
    },
    "POST /solo/ID/next": () => {
      round += 1;
      return { body: run(round, "loading", [...done]) };
    },
  });
  render(<Locations />);
  expect(await screen.findByText("No runs yet.")).toBeTruthy();
  expect(screen.getByText(/Playing as a guest/)).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Start a run" }));
  expect(await screen.findByText("Round 1 of 5")).toBeTruthy();
  const guessButton = await screen.findByRole("button", {
    name: "Click the map to place your pin",
  });
  expect((guessButton as HTMLButtonElement).disabled).toBe(true);
  expect(screen.getByText(/^\d+s$/)).toBeTruthy();
  clickMap();
  fireEvent.click(screen.getByRole("button", { name: "Guess" }));
  expect(await screen.findByText("+4,000")).toBeTruthy();
  expect(screen.getByText("12 blocks away.")).toBeTruthy();
  expect(screen.getByText("Hub · captured by Jaminul")).toBeTruthy();
  const posted = fetcher.mock.calls.find(([url]) =>
    String(url).endsWith("/guess"),
  );
  expect(JSON.parse(posted?.[1]?.body as string)).toEqual({
    version: 1,
    round: 1,
    x: 100,
    z: 50,
  });
  for (let number = 2; number <= 5; number += 1) {
    fireEvent.click(
      await screen.findByRole("button", {
        name: number === 5 ? "Last round" : "Next round",
      }),
    );
    expect(await screen.findByText(`Round ${number} of 5`)).toBeTruthy();
    await screen.findByRole("button", {
      name: "Click the map to place your pin",
    });
    clickMap();
    fireEvent.click(screen.getByRole("button", { name: "Guess" }));
    if (number === 2)
      expect(
        await screen.findByText("Wrong island: you picked Backwater Bayou."),
      ).toBeTruthy();
  }
  expect(await screen.findByText("16,000 of 25,000")).toBeTruthy();
  expect(screen.getByText("Best 16,000")).toBeTruthy();
  expect(localStorage.getItem("mithril.locations.best")).toBe("16000");
  fireEvent.click(screen.getByRole("button", { name: "Done" }));
  expect(await screen.findByText("Best 16,000")).toBeTruthy();
});

it("asks for the result once time runs out", async () => {
  serve({
    "GET /world": { body: world },
    "GET /me": { body: { version: 1, kind: "guest", name: null, solo: null } },
    "POST /solo": { body: run(1, "loading", []) },
    "POST /solo/ID/ready": {
      body: run(1, "playing", [], { deadline: now() - 5 }),
    },
    "GET /solo/ID": {
      body: run(1, "revealed", [
        result(0, { pin: null, distance: null, guessed: null }),
      ]),
    },
  });
  render(<Locations />);
  fireEvent.click(await screen.findByRole("button", { name: "Start a run" }));
  expect(await screen.findByText("No guess in time.")).toBeTruthy();
});

it("shows a linked player's best and says when a run beats it", async () => {
  const best = { best: 20_000, runs: 3, average: 15_000 };
  serve({
    "GET /world": { body: world },
    "GET /me": {
      body: { version: 1, kind: "linked", name: "Alice", solo: best },
    },
    "POST /solo": {
      body: run(
        5,
        "finished",
        Array.from({ length: 5 }, () => result(4800)),
        {
          best: { best: 24_000, runs: 4, average: 17_250, new_best: true },
        },
      ),
    },
  });
  render(<Locations />);
  expect(
    await screen.findByText(/Best 20,000 · Average 15,000 · 3 runs/),
  ).toBeTruthy();
  expect(screen.queryByText(/Playing as a guest/)).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Start a run" }));
  expect(
    await screen.findByText("New best! Best 24,000 · Average 17,250"),
  ).toBeTruthy();
  expect(localStorage.getItem("mithril.locations.best")).toBeNull();
});

it("goes back to the start when the run has ended, and reports errors", async () => {
  serve({
    "GET /world": { body: world },
    "GET /me": { body: { version: 1, kind: "guest", name: null, solo: null } },
    "POST /solo": { body: run(1, "loading", []) },
    "POST /solo/ID/ready": {
      status: 404,
      body: { detail: "This run has ended. Start a new one." },
    },
  });
  render(<Locations />);
  fireEvent.click(await screen.findByRole("button", { name: "Start a run" }));
  expect(await screen.findByRole("alert")).toHaveProperty(
    "textContent",
    "This run has ended. Start a new one.",
  );
  expect(screen.getByRole("button", { name: "Start a run" })).toBeTruthy();
});

it("explains when the game isn't ready", async () => {
  serve({
    "GET /world": {
      status: 503,
      body: { detail: "The game is getting ready. Try again in a moment." },
    },
  });
  render(<Locations />);
  expect(await screen.findByRole("alert")).toHaveProperty(
    "textContent",
    "The game is getting ready. Try again in a moment.",
  );
  await waitFor(() =>
    expect(
      (screen.getByRole("button", { name: "Start a run" }) as HTMLButtonElement)
        .disabled,
    ).toBe(true),
  );
});
