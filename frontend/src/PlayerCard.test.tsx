import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import fixture from "../../contracts/player-card-v1.json";
import { PlayerCard } from "./PlayerCard";
import { Account } from "./account";
import { formatTime, parsePlayerCard } from "./playerCardApi";

vi.mock("./SkinPreview", () => ({ SkinPreview: () => <div>Skin</div> }));
beforeEach(() => {
  HTMLDialogElement.prototype.showModal = function () {
    this.setAttribute("open", "");
  };
  HTMLDialogElement.prototype.close = function () {
    this.removeAttribute("open");
  };
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

it("only opens and requests the card when clicking the account name, then restores focus", async () => {
  const fetcher = vi.fn((url: string) =>
    Promise.resolve(
      new Response(
        JSON.stringify(
          url.endsWith("session")
            ? { authenticated: true, user: fixture.user }
            : fixture,
        ),
      ),
    ),
  );
  vi.stubGlobal("fetch", fetcher);
  render(<Account />);
  const name = await screen.findByRole("button", { name: "TestPlayer" });
  expect(screen.queryByRole("dialog")).toBeNull();
  expect(fetcher.mock.calls.some(([url]) => url.endsWith("player-card"))).toBe(
    false,
  );
  fireEvent.click(name);
  const card = await screen.findByRole("dialog", { name: "TestPlayer" });
  expect(await within(card).findByText("42.50")).toBeTruthy();
  expect(within(card).getByText((12345).toLocaleString())).toBeTruthy();
  expect(within(card).getByText((1000).toLocaleString())).toBeTruthy();
  expect(within(card).getByText("Highest recorded")).toBeTruthy();
  expect(within(card).getByText("4m 20.00s")).toBeTruthy();
  expect(within(card).getByText("4m 50.00s")).toBeTruthy();
  expect(within(card).getByText("No mod data synced yet.")).toBeTruthy();
  expect(within(card).getByText("Solo clear PB")).toBeTruthy();
  expect(within(card).getByText("SS time")).toBeTruthy();
  expect(within(card).getByText("Terminal phase PB")).toBeTruthy();
  fireEvent.click(within(card).getByRole("button", { name: "F7" }));
  expect(
    within(card)
      .getByRole("button", { name: "F7" })
      .getAttribute("aria-pressed"),
  ).toBe("true");
  fireEvent.click(
    within(card).getByRole("button", { name: "Close player card" }),
  );
  expect(screen.queryByRole("dialog")).toBeNull();
  expect(document.activeElement).toBe(name);
  expect(document.body.style.overflow).toBe("");
});

it("shows a safe error and retries without rendering upstream details", async () => {
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockResolvedValueOnce(new Response("private", { status: 503 }))
      .mockResolvedValueOnce(new Response(JSON.stringify(fixture))),
  );
  render(<PlayerCard user={fixture.user} onClose={() => {}} />);
  expect(await screen.findByRole("alert")).toBeTruthy();
  expect(screen.queryByText("private")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Try again" }));
  expect(await screen.findByText("42.50")).toBeTruthy();
});

it("handles session expiry and Escape without inventing stats", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(new Response("", { status: 401 })),
  );
  const close = vi.fn();
  render(<PlayerCard user={fixture.user} onClose={close} />);
  expect(
    await screen.findByText("Your session ended. Sign in again."),
  ).toBeTruthy();
  fireEvent(screen.getByRole("dialog"), new Event("cancel", { bubbles: true }));
  expect(close).toHaveBeenCalledOnce();
});

it("renders missing data as unknown, not zero, and cancels in-flight requests", async () => {
  let signal: AbortSignal | undefined;
  vi.stubGlobal(
    "fetch",
    vi.fn((_url, options) => {
      signal = options.signal;
      return Promise.resolve(
        new Response(
          JSON.stringify({
            ...fixture,
            profile: null,
            catacombs: null,
            secrets: null,
            magical_power: null,
          }),
        ),
      );
    }),
  );
  const view = render(<PlayerCard user={fixture.user} onClose={() => {}} />);
  expect(await screen.findByText("No SkyBlock profile found.")).toBeTruthy();
  await waitFor(() => expect(screen.queryByText("42.50")).toBeNull());
  view.unmount();
  expect(signal?.aborted).toBe(true);
});

it("validates the shared contract and rejects mixed identities, bad numbers and duplicate floors", () => {
  expect(parsePlayerCard(fixture, fixture.user.uuid)).toEqual(fixture);
  for (const invalid of [
    null,
    { ...fixture, version: 2 },
    { ...fixture, secrets: -1 },
    { ...fixture, magical_power: Infinity },
    { ...fixture, floors: Array(14).fill(fixture.floors[0]) },
  ]) {
    expect(() => parsePlayerCard(invalid, fixture.user.uuid)).toThrow();
  }
  expect(() => parsePlayerCard(fixture, "f".repeat(32))).toThrow();
});

it("formats minutes and carries rounded seconds without showing missing values as zero", () => {
  expect(formatTime(null)).toBe("—");
  expect(formatTime(20400)).toBe("20.40s");
  expect(formatTime(59999)).toBe("1m 0.00s");
  expect(formatTime(290000)).toBe("4m 50.00s");
  expect(formatTime(62010)).toBe("1m 2.01s");
});

it("shows synced account records independently for normal and master mode", async () => {
  const data = structuredClone(fixture);
  const floors = data.floors.map((row) => ({
    ...row,
    solo_clear_ms:
      row.floor === "M7" ? 320000 : row.floor === "F7" ? 300000 : null,
    terminals_ms:
      row.floor === "M7" ? 42000 : row.floor === "F7" ? 40000 : null,
  }));
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          ...data,
          floors,
          mod_records_available: true,
        }),
      ),
    ),
  );
  render(<PlayerCard user={fixture.user} onClose={() => {}} />);
  expect(await screen.findByText("5m 20.00s")).toBeTruthy();
  expect(screen.getByText("42.00s")).toBeTruthy();
  expect(screen.queryByText("No mod data synced yet.")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "F7" }));
  expect(screen.getByText("5m 0.00s")).toBeTruthy();
  expect(screen.getByText("40.00s")).toBeTruthy();
});
