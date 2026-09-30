import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { App } from "./App";
import { SlayerProfits } from "./SlayerProfits";

const market = {
  version: 1,
  bazaar: { REVENANT_FLESH: { instant: 10, offer: 20 } },
  npc: { FOUL_FLESH: 25000 },
  auctions: {
    "Warden Heart": { price: 100000000, source: "BIN", samples: 3, spread: 0 },
  },
  pets: [
    {
      name: "Synthetic pet",
      rarity: "LEGENDARY",
      startLevel: 1,
      endLevel: 100,
      startPrice: 1000000,
      endPrice: 3000000,
      requiredXp: 1000000,
      samples: 6,
    },
  ],
  feeds: Object.fromEntries(
    ["bazaar", "npc", "auctions", "sales"].map((k) => [
      k,
      { status: "ready", updated: 1800000000 },
    ]),
  ),
};
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  window.history.replaceState(null, "", "/");
});
function mockMarket() {
  const fetcher = vi
    .fn()
    .mockResolvedValue(new Response(JSON.stringify(market)));
  vi.stubGlobal("fetch", fetcher);
  return fetcher;
}

it("labels provisional history and shows Kat costs without treating Common resale as profit", async () => {
  const value = {
    ...market,
    pets: [
      {
        ...market.pets[0],
        rarity: "COMMON",
        endRarity: "LEGENDARY",
        historyHours: 2,
        requiredXp: 25353230,
        kat: {
          coins: 100000,
          materials: 200000,
          flowers: 4,
          flowerCost: 400000,
          total: 700000,
        },
      },
    ],
  };
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(new Response(JSON.stringify(value))),
  );
  render(<SlayerProfits />);
  await screen.findByText(/Common → Legendary · Kat/);
  expect(screen.getByText("700K upgrades incl. 4 flowers")).toBeTruthy();
  expect(
    screen.getByText("Provisional · building 7-day price history"),
  ).toBeTruthy();
});

it.each(["/slayer-profits", "/slayer-profits/", "/slayerprofits"])(
  "opens %s without sign-in",
  async (path) => {
    window.history.replaceState(null, "", path);
    const fetcher = mockMarket();
    render(<App />);
    expect(
      screen.getByRole("heading", { level: 1, name: "Slayer profits" }),
    ).toBeTruthy();
    expect(
      screen
        .getByRole("link", { name: "Slayer profits" })
        .getAttribute("aria-current"),
    ).toBe("page");
    await screen.findByText(/Market prices loaded/);
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(fetcher.mock.calls[0]?.[0]).toBe("/api/v1/slayer-prices");
    expect(fetcher.mock.calls[0]?.[1].credentials).toBe("omit");
    expect(document.title).toBe("Slayer profits · Mithril");
  },
);

it("recalculates pricing and throughput, resets unsupported tiers and meters", async () => {
  mockMarket();
  render(<SlayerProfits />);
  await screen.findByText(/Market prices loaded/);
  const row = () => screen.getByRole("row", { name: /^Revenant Flesh/ });
  expect(within(row()).getByText("38.1K")).toBeTruthy();
  fireEvent.change(screen.getByLabelText("Bazaar pricing"), {
    target: { value: "offer" },
  });
  expect(within(row()).getByText("76.2K")).toBeTruthy();
  fireEvent.change(screen.getByLabelText("RNG meter"), {
    target: { value: "Warden Heart" },
  });
  expect(screen.getByText(/Warden Heart: .*XP guarantee/)).toBeTruthy();
  fireEvent.change(screen.getByLabelText("Slayer"), { target: { value: "2" } });
  expect((screen.getByLabelText("Tier") as HTMLSelectElement).value).toBe("4");
  expect((screen.getByLabelText("RNG meter") as HTMLSelectElement).value).toBe(
    "",
  );
  fireEvent.change(screen.getByLabelText("Tier"), { target: { value: "1" } });
  expect(
    (screen.getByLabelText("RNG meter") as HTMLSelectElement).disabled,
  ).toBe(true);
  fireEvent.change(screen.getByLabelText("Bosses/hr"), {
    target: { value: "0" },
  });
  expect(
    within(
      screen.getByRole("heading", { name: "Total net/hr" }).parentElement!,
    ).getByText("+0"),
  ).toBeTruthy();
  fireEvent.change(screen.getByLabelText("Magic Find"), {
    target: { value: "-1" },
  });
  expect(screen.getByRole("alert").textContent).toContain("Enter Magic Find");
});

it("shows missing prices on failure and supports retry", async () => {
  const fetcher = vi
    .fn()
    .mockRejectedValueOnce(new Error("offline"))
    .mockImplementation(() =>
      Promise.resolve(new Response(JSON.stringify(market))),
    );
  vi.stubGlobal("fetch", fetcher);
  render(<SlayerProfits />);
  await screen.findByText(/Prices incomplete or stale/);
  expect(screen.getByText("Partial estimate")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Refresh prices" }));
  await screen.findByText(/Market prices loaded/);
  expect(fetcher).toHaveBeenCalledTimes(2);
});

it("updates independent mayor perks and EXP Share-only totals without refetching prices", async () => {
  const fetcher = mockMarket();
  render(<SlayerProfits />);
  await screen.findByText(/Market prices loaded/);
  const fees = screen.getByRole("heading", {
    name: "Quest fees/hr",
  }).parentElement!;
  expect(within(fees).getByText("−6M")).toBeTruthy();
  fireEvent.change(screen.getByLabelText("RNG meter"), {
    target: { value: "Warden Heart" },
  });
  const strategy = screen.getByRole("region", { name: "RNG strategy" });
  expect(within(strategy).getByText("Cutoff strategy")).toBeTruthy();
  const before = strategy.textContent;
  fireEvent.click(screen.getByLabelText("+25% RNG meter XP"));
  expect(strategy.textContent).not.toBe(before);
  expect(within(fees).getByText("−6M")).toBeTruthy();
  expect(
    (screen.getByLabelText("Half-price quests") as HTMLInputElement).checked,
  ).toBe(false);
  fireEvent.click(screen.getByLabelText("Half-price quests"));
  expect(within(fees).getByText("−3M")).toBeTruthy();
  expect(within(fees).getByText("60 bosses/hr · 50K/boss")).toBeTruthy();
  fireEvent.click(screen.getByLabelText("3 EXP Share slots (+10% rate)"));
  expect(screen.getByText("1,914,192 XP/hr")).toBeTruthy();
  expect(
    (screen.getByLabelText("+35% pet XP") as HTMLInputElement).checked,
  ).toBe(false);
  fireEvent.click(screen.getByLabelText("+35% pet XP"));
  expect(screen.getByText("2,584,159 XP/hr")).toBeTruthy();
  fireEvent.click(screen.getByLabelText("Exclude main pet"));
  expect(screen.getByText("1,359,439 XP/hr")).toBeTruthy();
  expect(screen.getByText(/EXP Share only · 3 slots/)).toBeTruthy();
  fireEvent.click(screen.getByLabelText("Exclude main pet"));
  expect(screen.getByText("2,584,159 XP/hr")).toBeTruthy();
  expect(fetcher).toHaveBeenCalledTimes(1);
});

it("aborts pending price requests when leaving the page", async () => {
  const fetcher = vi.fn(() => new Promise(() => {}));
  vi.stubGlobal("fetch", fetcher);
  const view = render(<SlayerProfits />);
  await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(1));
  const signal = (
    fetcher.mock.calls as unknown as [string, { signal: AbortSignal }][]
  )[0]![1].signal;
  view.unmount();
  expect(signal.aborted).toBe(true);
});
