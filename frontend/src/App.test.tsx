import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import fixture from "../../contracts/health-v1.json";
import { App } from "./App";

beforeEach(() => window.history.replaceState(null, "", "/party-finder"));

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  window.history.replaceState(null, "", "/");
});

it("keeps the home page separate with a link to party finder", () => {
  window.history.replaceState(null, "", "/");
  const fetcher = vi.fn();
  vi.stubGlobal("fetch", fetcher);
  render(<App />);
  expect(
    screen.getByRole("link", { name: "Party finder" }).getAttribute("href"),
  ).toBe("/party-finder");
  expect(
    screen.queryByRole("heading", { name: "Dungeon party finder" }),
  ).toBeNull();
  expect(screen.queryByRole("status")).toBeNull();
  expect(fetcher).not.toHaveBeenCalled();
  expect(document.title).toBe("Mithril");
  expect(screen.getByRole("heading", { level: 1 }).textContent).toBe(
    "Party Finder",
  );
  expect(screen.queryByText(/SkyBlock|In Minecraft and on the web/)).toBeNull();
});

it("accepts a direct party-finder URL with a trailing slash", async () => {
  window.history.replaceState(null, "", "/party-finder/?test=1");
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockImplementation((url: string) =>
        Promise.resolve(
          new Response(
            JSON.stringify(
              url.endsWith("/health") ? fixture : { authenticated: false },
            ),
          ),
        ),
      ),
  );
  render(<App />);
  expect(await screen.findByText("Service online")).toBeTruthy();
  expect(document.title).toBe("MithrilPF · Party finder");
  expect(
    screen.getByRole("link", { name: "MithrilPF" }).getAttribute("href"),
  ).toBe("/");
});

it("does not show party finder at unknown paths", () => {
  window.history.replaceState(null, "", "/not-a-page");
  const fetcher = vi.fn();
  vi.stubGlobal("fetch", fetcher);
  render(<App />);
  expect(screen.getByRole("heading", { name: "Page not found" })).toBeTruthy();
  expect(fetcher).not.toHaveBeenCalled();
});

it("shows the workspace without suggesting that party matching is already live", async () => {
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockImplementation((url: string) =>
        Promise.resolve(
          new Response(
            JSON.stringify(
              url.endsWith("/health") ? fixture : { authenticated: false },
            ),
          ),
        ),
      ),
  );
  render(<App />);
  expect(screen.getByText("In development.")).toBeTruthy();
  expect(screen.queryByText("Dungeons")).toBeNull();
  expect(
    screen.getByRole("heading", { name: "Dungeon party finder" }),
  ).toBeTruthy();
  expect(await screen.findByText("Service online")).toBeTruthy();
  expect(screen.getByRole("region", { name: "Parties" })).toBeTruthy();
  expect(screen.getByRole("heading", { name: "Your account" })).toBeTruthy();
  expect(
    screen.getByText("Party browsing and matching are coming next."),
  ).toBeTruthy();
  expect(
    screen
      .getByRole("link", { name: "Party finder" })
      .getAttribute("aria-current"),
  ).toBe("page");
  expect(
    screen.queryByText(/a party worth|foundation is in place|find your group/i),
  ).toBeNull();
  expect(screen.queryByRole("button", { name: /sign in|search/i })).toBeNull();
});

it("keeps a working primary destination and keyboard skip link on the home page", () => {
  window.history.replaceState(null, "", "/");
  render(<App />);
  expect(
    screen
      .getByRole("link", { name: "Open party finder" })
      .getAttribute("href"),
  ).toBe("/party-finder");
  expect(
    screen.getByRole("link", { name: "Skip to content" }).getAttribute("href"),
  ).toBe("#main");
  expect(screen.getByRole("main").id).toBe("main");
  expect(
    screen.getByRole("link", { name: "Cookies" }).getAttribute("href"),
  ).toBe("/cookies");
});

it("keeps the cookie policy available in the shared page layout", () => {
  window.history.replaceState(null, "", "/cookies");
  render(<App />);
  expect(
    screen.getByRole("heading", { name: "Cookie policy", level: 1 }),
  ).toBeTruthy();
  expect(screen.getByText("__Host-mithril_session")).toBeTruthy();
});

it("shows an unavailable state without leaking an error body", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockRejectedValue(new Error("private response")),
  );
  render(<App />);
  expect(await screen.findByText("Service unavailable")).toBeTruthy();
  expect(screen.queryByText("private response")).toBeNull();
});

it("cancels the request on unmount", () => {
  const fetcher = vi.fn().mockImplementation(() => new Promise(() => {}));
  vi.stubGlobal("fetch", fetcher);
  const view = render(<App />);
  const signal = fetcher.mock.calls.find(([url]) =>
    url.endsWith("/health"),
  )?.[1].signal as AbortSignal;
  view.unmount();
  expect(signal.aborted).toBe(true);
});
