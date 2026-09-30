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
  pets: [],
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
  fireEvent.change(screen.getByLabelText("Bosses per hour"), {
    target: { value: "0" },
  });
  expect(screen.getByText("+0")).toBeTruthy();
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
  await screen.findByText(/Some market prices are unavailable/);
  expect(screen.getByText("Partial estimate · coins")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Refresh prices" }));
  await screen.findByText(/Market prices loaded/);
  expect(fetcher).toHaveBeenCalledTimes(2);
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
