import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { RunMap } from "./RunMap";
import { App } from "./App";
import timedMap from "../../contracts/run-map-v2.json";

const id = "a".repeat(43);
const data = {
  version: 1,
  record: {
    id,
    uuid: "a".repeat(32),
    name: "Synthetic",
    floor: "F7",
    ticks: 1801,
    created: 1700000000,
  },
  map: {
    version: 1,
    rooms: [
      {
        tiles: [0, 1, 7],
        name: "Synthetic room",
        type: "NORMAL",
        state: "CLEARED",
        secrets_found: 3,
        secrets_total: 5,
      },
      {
        tiles: [2],
        name: "Puzzle",
        type: "PUZZLE",
        state: "COMPLETE",
        secrets_found: 0,
        secrets_total: 0,
      },
      {
        tiles: [8],
        name: null,
        type: "UNKNOWN",
        state: "UNKNOWN",
        secrets_found: null,
        secrets_total: null,
      },
    ],
    doors: [
      { a: 1, b: 2, type: "WITHER" },
      { a: 2, b: 8, type: "BLOOD" },
    ],
  },
};

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  window.history.replaceState(null, "", "/");
});

function mock(value: unknown = data, status = 200) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response(JSON.stringify(value), { status })),
  );
}

it("renders a public linked PB with geometry and room details", async () => {
  mock();
  render(<RunMap recordId={id} />);
  await screen.findByRole("heading", { name: "1:30.050 by Synthetic" });
  expect(fetch).toHaveBeenCalledWith(
    `/api/v1/records/solo/${id}`,
    expect.objectContaining({ cache: "no-store" }),
  );
  expect(
    screen.getByRole("img", { name: "Dungeon layout at 300 score" }),
  ).toBeTruthy();
  expect(screen.getByText("3 tiles")).toBeTruthy();
  const door = document.querySelector("line");
  expect(door?.getAttribute("x1")).toBe("118");
  expect(door?.getAttribute("x2")).toBe("130");
  fireEvent.click(
    screen.getByRole("button", { name: "Puzzle 0/0 secrets · Complete" }),
  );
  expect(screen.getByRole("heading", { name: "Puzzle" })).toBeTruthy();
  expect(screen.getByText("1 tile")).toBeTruthy();
  fireEvent.click(screen.getByRole("link", { name: "Unknown: ?/? secrets" }));
  expect(
    screen.getByText("Part of this room’s secret counter was not captured."),
  ).toBeTruthy();
});

it("routes map URLs and explains retired or missing maps", async () => {
  mock({ ...data, map: null });
  window.history.replaceState(null, "", `/runs/${id}`);
  render(<App />);
  expect(
    await screen.findByRole("heading", { name: "Map unavailable" }),
  ).toBeTruthy();
  expect(screen.getByText(/Maps are kept only/)).toBeTruthy();
});

it.each([
  [404, "This run is unavailable."],
  [503, "Could not load this run. Try again shortly."],
])("handles HTTP %s", async (status, message) => {
  mock({}, status as number);
  render(<RunMap recordId={id} />);
  expect((await screen.findByRole("alert")).textContent).toBe(message);
});

it("rejects unsupported maps and escapes room labels", async () => {
  mock({ ...data, map: { ...data.map, version: 3 } });
  render(<RunMap recordId={id} />);
  expect((await screen.findByRole("alert")).textContent).toContain(
    "unsupported map format",
  );
  cleanup();
  const changed = structuredClone(data);
  changed.map.rooms[0]!.name = "<script>bad()</script>";
  mock(changed);
  render(<RunMap recordId={id} />);
  expect(
    await screen.findByRole("heading", { name: "<script>bad()</script>" }),
  ).toBeTruthy();
  expect(document.querySelector("script")).toBeNull();
});

it("shows frozen dungeon totals and room plus transit times matching the PB", async () => {
  mock({ ...data, record: { ...data.record, ticks: 300 }, map: timedMap });
  render(<RunMap recordId={id} />);
  await screen.findByRole("heading", { name: "0:15.000 by Synthetic" });
  expect(screen.getByLabelText("Dungeon totals at 300 score").textContent).toBe(
    "Secrets collected3Total secrets5Crypts killed5",
  );
  expect(
    screen.getByText(/Rooms/, { selector: ".run-timing" }).textContent,
  ).toBe("Rooms 0:14.000 + Transit / unmapped 0:01.000 = Run 0:15.000");
  expect(screen.getByText("Time in room").nextElementSibling?.textContent).toBe(
    "0:06.000",
  );
  fireEvent.click(
    screen.getByRole("button", {
      name: "Puzzle 0:08.000 · 0/0 secrets · Complete",
    }),
  );
  expect(screen.getByText("Time in room").nextElementSibling?.textContent).toBe(
    "0:08.000",
  );
  expect(screen.getByText(/include repeat visits/)).toBeTruthy();
});

it("distinguishes old maps and missing counters from measured zeros", async () => {
  mock();
  render(<RunMap recordId={id} />);
  await screen.findByText(
    "Room timing and dungeon totals were not recorded for this run.",
  );
  expect(screen.getByText("Not recorded")).toBeTruthy();
  cleanup();
  mock({
    ...data,
    map: {
      ...timedMap,
      stats: {
        ...timedMap.stats,
        secrets_found: null,
        secrets_total: null,
        crypts: null,
      },
    },
  });
  render(<RunMap recordId={id} />);
  expect(await screen.findAllByText("Not captured")).toHaveLength(3);
  cleanup();
  mock({
    ...data,
    map: {
      ...timedMap,
      stats: {
        ...timedMap.stats,
        secrets_found: 0,
        secrets_total: 0,
        crypts: 0,
      },
    },
  });
  render(<RunMap recordId={id} />);
  await screen.findByLabelText("Dungeon totals at 300 score");
  expect(screen.queryByText("Not captured")).toBeNull();
});

it("handles a network failure without leaving a loading page", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockRejectedValue(new DOMException("aborted", "AbortError")),
  );
  render(<RunMap recordId={id} />);
  expect((await screen.findByRole("alert")).textContent).toContain(
    "Try again shortly",
  );
});

it("fills the center of a two by two room", async () => {
  const changed = structuredClone(data);
  changed.map.rooms[0]!.tiles = [0, 1, 6, 7];
  mock(changed);
  render(<RunMap recordId={id} />);
  await screen.findByText("4 tiles");
  expect(
    document.querySelector('rect[width="108"][height="108"]'),
  ).toBeTruthy();
});
