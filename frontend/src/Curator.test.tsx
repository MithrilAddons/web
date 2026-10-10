import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import contract from "../../contracts/curator-v1.json";
import { Curator } from "./Curator";

const ITEMS = [
  ["SYNTHESIZER_V2", "Synthesizer v2"],
  ["SYNTHESIZER_V3", "Synthesizer v3"],
  ["HYPERION", "Hyperion"],
  ["SHADOW_FURY", "Shadow Fury"],
];
const playing = {
  ...contract.playing,
  resets_at: Date.now() / 1000 + 3 * 3600,
};
const solved = { ...contract.solved, resets_at: Date.now() / 1000 + 3600 };

type Reply = { status?: number; body: unknown };
type Routes = Record<string, Reply | ((init?: RequestInit) => Reply)>;

function serve(routes: Routes) {
  const fetcher = vi.fn((url: string, init?: RequestInit) => {
    const path = url.replace("/api/v1/games/curator", "").split("?")[0] ?? "";
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

function narrow(matches: boolean) {
  vi.stubGlobal(
    "matchMedia",
    vi.fn(() => ({
      matches,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })),
  );
}

beforeEach(() => localStorage.clear());
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  localStorage.clear();
});

it("plays a round on a wide screen and shares the result", async () => {
  const writeText = vi.fn(() => Promise.resolve());
  vi.stubGlobal("navigator", { clipboard: { writeText } });
  const fetcher = serve({
    "GET /today": { body: playing },
    "GET /catalog": { body: { version: 1, catalog: "3:1", items: ITEMS } },
    "POST /guess": { body: solved },
  });
  render(<Curator />);
  expect(await screen.findByText("Curator #1")).toBeTruthy();
  expect(screen.getByText("1 of 10 guesses")).toBeTruthy();
  expect(screen.getByText(/9 guesses left · New item in 3h/)).toBeTruthy();
  const grid = screen.getByRole("table");
  expect(within(grid).getByText("Synthesizer v2")).toBeTruthy();
  expect(within(grid).getByText("family")).toBeTruthy();
  expect(
    within(grid).getByLabelText(
      "Market value: 3,100,000. The answer is worth more",
    ),
  ).toBeTruthy();
  const box = screen.getByRole("combobox");
  await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(2));
  fireEvent.change(box, { target: { value: "synth" } });
  // Already-guessed items are left out of the list.
  const options = screen.getAllByRole("option");
  expect(options.map((option) => option.textContent)).toEqual([
    "Synthesizer v3",
  ]);
  fireEvent.keyDown(box, { key: "Enter" });
  expect((box as HTMLInputElement).value).toBe("Synthesizer v3");
  fireEvent.keyDown(box, { key: "Enter" });
  expect(await screen.findByText("Solved in 2 of 10")).toBeTruthy();
  const posted = fetcher.mock.calls.find(([, init]) => init?.method === "POST");
  expect(JSON.parse(posted?.[1]?.body as string)).toEqual({
    version: 1,
    day: "2027-01-15",
    item: "SYNTHESIZER_V3",
  });
  expect(screen.getByText("Synthesizer v3", { selector: "p" })).toBeTruthy();
  expect(screen.getByText("EPIC NECKLACE")).toBeTruthy();
  expect(screen.getByText("Streak 1 · Best 1")).toBeTruthy();
  expect(screen.getByText("Played 1 · Solved 100%")).toBeTruthy();
  expect(screen.queryByRole("combobox")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Copy result" }));
  expect(await screen.findByRole("button", { name: "Copied" })).toBeTruthy();
  expect(writeText).toHaveBeenCalledWith(
    expect.stringContaining("Curator #1 2/10"),
  );
});

it("uses the keyboard and explains a name that isn't in the list", async () => {
  serve({
    "GET /today": { body: playing },
    "GET /catalog": { body: { version: 1, catalog: "3:1", items: ITEMS } },
    "POST /guess": { status: 409, body: { detail: "Already guessed" } },
  });
  render(<Curator />);
  const box = await screen.findByRole("combobox");
  await waitFor(() => {
    fireEvent.change(box, { target: { value: "s" } });
    expect(screen.getAllByRole("option")).toHaveLength(2);
  });
  fireEvent.keyDown(box, { key: "ArrowDown" });
  expect(screen.getAllByRole("option")[1]?.getAttribute("aria-selected")).toBe(
    "true",
  );
  fireEvent.keyDown(box, { key: "ArrowUp" });
  fireEvent.keyDown(box, { key: "Tab" });
  expect((box as HTMLInputElement).value).toBe("Shadow Fury");
  fireEvent.change(box, { target: { value: "hyp" } });
  fireEvent.keyDown(box, { key: "Escape" });
  expect(screen.queryByRole("listbox")).toBeNull();
  fireEvent.change(box, { target: { value: "nothing like it" } });
  fireEvent.click(screen.getByRole("button", { name: "Guess" }));
  expect(await screen.findByRole("alert")).toHaveProperty(
    "textContent",
    "Pick an item from the list",
  );
  fireEvent.change(box, { target: { value: "Hyperion" } });
  fireEvent.click(screen.getByRole("button", { name: "Guess" }));
  expect(await screen.findByText("Already guessed")).toBeTruthy();
  fireEvent.change(box, { target: { value: "hyp" } });
  fireEvent.mouseEnter(screen.getByRole("option"));
  fireEvent.mouseDown(screen.getByRole("option"));
  expect((box as HTMLInputElement).value).toBe("Hyperion");
  fireEvent.blur(box);
});

it("shows a clue summary, one-line guesses and the box at the bottom on phones", async () => {
  narrow(true);
  serve({
    "GET /today": { body: playing },
    "GET /catalog": { body: { version: 1, catalog: "3:1", items: ITEMS } },
  });
  render(<Curator />);
  const summary = await screen.findByRole("region", { name: "What you know" });
  expect(within(summary).getByText("Epic")).toBeTruthy();
  expect(within(summary).getByText("over 3.1M")).toBeTruthy();
  const row = screen.getByRole("button", { name: /Synthesizer v2/ });
  expect(row.getAttribute("aria-expanded")).toBe("true");
  expect(
    screen.getByText("Market value: 3,100,000. The answer is worth more"),
  ).toBeTruthy();
  fireEvent.click(row);
  expect(row.getAttribute("aria-expanded")).toBe("false");
  fireEvent.click(row);
  expect(row.getAttribute("aria-expanded")).toBe("true");
  const box = screen.getByRole("combobox");
  expect(box.closest(".curator-dock")).toBeTruthy();
  await waitFor(() => {
    fireEvent.change(box, { target: { value: "synth" } });
    expect(screen.getAllByRole("option")).toHaveLength(1);
  });
  fireEvent.keyDown(box, { key: "ArrowUp" });
  fireEvent.keyDown(box, { key: "ArrowDown" });
});

it("offers the next item once the day turns over", async () => {
  let today: unknown = playing;
  serve({
    "GET /today": () => ({ body: today }),
    "GET /catalog": { body: { version: 1, catalog: "3:1", items: ITEMS } },
    "POST /guess": { status: 409, body: { detail: "A new item is ready" } },
  });
  render(<Curator />);
  const box = await screen.findByRole("combobox");
  await waitFor(() => {
    fireEvent.change(box, { target: { value: "Hyperion" } });
    fireEvent.keyDown(box, { key: "Enter" });
    expect(screen.getByText("A new item is ready")).toBeTruthy();
  });
  today = { ...playing, day: "2027-01-16", number: 2, guesses: [] };
  fireEvent.click(screen.getByRole("button", { name: "Load new item" }));
  expect(await screen.findByText("Curator #2")).toBeTruthy();
  expect(screen.queryByText("A new item is ready")).toBeNull();
});

it("asks signed-out visitors to link and still shows the leaderboard", async () => {
  serve({
    "GET /today": {
      status: 401,
      body: { detail: "Link your Minecraft account to play Curator" },
    },
    "GET /catalog": { status: 401, body: {} },
    "GET /leaderboard": {
      body: {
        ...contract.leaderboard,
        top: [{ ...contract.leaderboard.top[0], you: false }],
        stats: null,
      },
    },
  });
  render(<Curator />);
  expect(
    await screen.findByText("Link your Minecraft account to play Curator."),
  ).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Leaderboard" }));
  expect(await screen.findByText("January season")).toBeTruthy();
  expect(screen.getByText("Alice")).toBeTruthy();
  expect(screen.getByText("Link your Minecraft account")).toBeTruthy();
  expect(localStorage.getItem("mithril.curator.view")).toBe("leaderboard");
});

it("shows your season, a pinned row and when the season ends", async () => {
  localStorage.setItem("mithril.curator.view", "leaderboard");
  const top = Array.from({ length: 10 }, (_, index) => ({
    rank: index + 1,
    name: `Player${index}`,
    points: 10,
    solved: 1,
    played: 1,
    streak: 1,
    you: false,
  }));
  serve({
    "GET /leaderboard": {
      body: {
        ...contract.leaderboard,
        players: 12,
        top,
        you: {
          rank: 12,
          name: "Alice",
          points: 8,
          solved: 1,
          played: 2,
          streak: 0,
          you: true,
        },
        stats: {
          ...contract.leaderboard.stats,
          rank: 12,
          failed: 1,
          average: null,
        },
      },
    },
  });
  render(<Curator />);
  expect(await screen.findByText("Rank 12 of 12")).toBeTruthy();
  const alice = screen.getByText("Alice").closest("tr");
  expect(alice?.className).toBe("is-you is-pinned");
  expect(screen.getByLabelText("2 guesses: 1")).toBeTruthy();
  expect(screen.getByText("Not solved: 1")).toBeTruthy();
  expect(screen.getByText(/Season ends February 1/)).toBeTruthy();
});

it("covers the quiet states: preparing, banned, empty, offline", async () => {
  serve({
    "GET /today": {
      body: {
        version: 1,
        day: "2027-01-15",
        state: "preparing",
        resets_at: Date.now() / 1000 + 120,
      },
    },
    "GET /catalog": { body: { version: 1, catalog: "3:1", unchanged: true } },
  });
  const { unmount } = render(<Curator />);
  expect(
    await screen.findByText("Today’s item is being prepared…"),
  ).toBeTruthy();
  expect(screen.getByText("New item in 2m")).toBeTruthy();
  unmount();

  serve({ "GET /today": { status: 403, body: { detail: "Banned" } } });
  const banned = render(<Curator />);
  expect(
    await screen.findByText("This account can’t play Curator."),
  ).toBeTruthy();
  banned.unmount();

  serve({ "GET /today": { status: 500, body: "not json" } });
  const broken = render(<Curator />);
  expect(await screen.findByRole("alert")).toHaveProperty(
    "textContent",
    "Something went wrong. Try again.",
  );
  broken.unmount();

  localStorage.setItem("mithril.curator.view", "leaderboard");
  serve({
    "GET /leaderboard": {
      body: { ...contract.leaderboard, top: [], stats: null },
    },
  });
  const empty = render(<Curator />);
  expect(
    await screen.findByText("No finished rounds yet this season"),
  ).toBeTruthy();
  empty.unmount();

  serve({});
  render(<Curator />);
  expect(await screen.findByRole("alert")).toHaveProperty(
    "textContent",
    "Can't reach Mithril. Your guesses so far are saved.",
  );
});

it("keeps the item list until the catalog changes", async () => {
  const fetcher = serve({
    "GET /today": { body: playing },
    "GET /catalog": { body: { version: 1, catalog: "3:1", items: ITEMS } },
  });
  const first = render(<Curator />);
  await waitFor(() =>
    expect(localStorage.getItem("mithril.curator.catalog")).toContain("3:1"),
  );
  first.unmount();
  serve({
    "GET /today": { body: playing },
    "GET /catalog": { body: { version: 1, catalog: "3:1", unchanged: true } },
  });
  render(<Curator />);
  const box = await screen.findByRole("combobox");
  await waitFor(() => {
    fireEvent.change(box, { target: { value: "hyp" } });
    expect(screen.getByRole("option").textContent).toBe("Hyperion");
  });
  expect(fetcher).toHaveBeenCalled();
  window.dispatchEvent(new Event("focus"));
});
