import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { Moderation } from "./Moderation";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const queue = [
  {
    day: "2027-01-01",
    item: "QUIET",
    name: "Quiet Ring",
    sales: 3,
    locked: true,
  },
  {
    day: "2027-01-02",
    item: "LOUD",
    name: "Loud Ring",
    sales: 9,
    locked: false,
  },
  { day: "2027-01-03", item: null, name: null, sales: null, locked: false },
];
const row = {
  rarity: "EPIC",
  museum: "COMBAT",
  sales: 3,
  list: null,
  status: "eligible",
  admin: false,
  new: true,
};

function server(role = "owner") {
  const fetcher = vi.fn(async (url: string, options?: RequestInit) => {
    const path = url.replace("/api/v1/moderation/", "");
    let body: object = {};
    if (path === "access")
      body = { role, moderators: [], network_bans_available: true };
    if (path === "curator")
      body = {
        sales_cutoff: 100,
        sales_since: "2026-12-20",
        counts: { eligible: 40, allowed: 2, popular: 7 },
        new: 5,
        queue,
      };
    if (path.startsWith("curator/items"))
      body = path.includes("offset=1")
        ? { total: 2, items: [{ ...row, id: "LOUD", name: "Loud Ring" }] }
        : { total: 2, items: [{ ...row, id: "QUIET", name: "Quiet Ring" }] };
    if (options?.body) body = {};
    return new Response(JSON.stringify(body), { status: 200 });
  });
  vi.stubGlobal("fetch", fetcher);
  return fetcher;
}

function posted(fetcher: ReturnType<typeof server>, path: string) {
  return fetcher.mock.calls
    .filter(([url, options]) => url.endsWith(path) && options?.body)
    .map(([, options]) => JSON.parse(String(options?.body)) as object);
}

async function open() {
  fireEvent.click(await screen.findByRole("button", { name: "Curator" }));
  await screen.findByText(/42 items in the answer pool/);
}

it("hides the Curator view from moderators", async () => {
  server("moderator");
  render(<Moderation />);
  await screen.findByRole("button", { name: "Audit log" });
  expect(screen.queryByRole("button", { name: "Curator" })).toBeNull();
});

it("shows the queue and rerolls or schedules coming days", async () => {
  const fetcher = server();
  render(<Moderation />);
  await open();
  expect(screen.getByText(/since 2026-12-20/)).toBeTruthy();
  expect(screen.getByText("No item available")).toBeTruthy();
  expect(screen.getAllByRole("button", { name: "Reroll" })).toHaveLength(2);
  fireEvent.click(screen.getAllByRole("button", { name: "Reroll" })[0]!);
  await waitFor(() =>
    expect(posted(fetcher, "curator/day")).toEqual([
      { version: 1, day: "2027-01-02", item: null },
    ]),
  );
  fireEvent.change(screen.getByLabelText("Day"), {
    target: { value: "2027-01-03" },
  });
  fireEvent.change(screen.getByLabelText("Item ID"), {
    target: { value: " SYNTHESIZER_V3 " },
  });
  fireEvent.click(screen.getByRole("button", { name: "Schedule item" }));
  await waitFor(() =>
    expect(posted(fetcher, "curator/day")[1]).toEqual({
      version: 1,
      day: "2027-01-03",
      item: "SYNTHESIZER_V3",
    }),
  );
  fireEvent.change(
    screen.getByLabelText("Too popular above (auction sales in 30 days)"),
    { target: { value: "25" } },
  );
  fireEvent.click(screen.getByRole("button", { name: "Save cut-off" }));
  await waitFor(() =>
    expect(posted(fetcher, "curator/settings")).toEqual([
      { version: 1, sales_cutoff: 25 },
    ]),
  );
  fireEvent.click(screen.getByRole("button", { name: "Mark all reviewed" }));
  await screen.findByText("Marked reviewed.");
});

it("lists items, pages through them and edits the lists", async () => {
  const fetcher = server();
  render(<Moderation />);
  await open();
  const table = screen.getAllByRole("table")[1]!;
  expect(within(table).getByText("QUIET")).toBeTruthy();
  expect(within(table).getByText("In pool")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Show more" }));
  await screen.findByText("LOUD", { selector: "code" });
  expect(screen.queryByRole("button", { name: "Show more" })).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Block Quiet Ring" }));
  await waitFor(() =>
    expect(posted(fetcher, "curator/list")).toEqual([
      { version: 1, item: "QUIET", list: "block" },
    ]),
  );
  fireEvent.change(screen.getByLabelText("Group"), {
    target: { value: "admin" },
  });
  await waitFor(() =>
    expect(
      fetcher.mock.calls.some(([url]) =>
        url.includes("curator/items?group=admin"),
      ),
    ).toBe(true),
  );
  fireEvent.change(screen.getByLabelText("Search"), {
    target: { value: "ring" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Search" }));
  await waitFor(() =>
    expect(fetcher.mock.calls.some(([url]) => url.includes("query=ring"))).toBe(
      true,
    ),
  );
});

it("shows request failures", async () => {
  const fetcher = server();
  render(<Moderation />);
  await open();
  fetcher.mockImplementationOnce(
    async () =>
      new Response(JSON.stringify({ detail: "No other item is available" }), {
        status: 404,
      }),
  );
  fireEvent.click(screen.getAllByRole("button", { name: "Reroll" })[0]!);
  await screen.findByText("No other item is available");
});
