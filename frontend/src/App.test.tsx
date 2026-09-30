import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import fixture from "../../contracts/health-v1.json";
import { App } from "./App";

beforeEach(() => window.history.replaceState(null, "", "/party-finder"));

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
  window.history.replaceState(null, "", "/");
});

it("links deployed branch builds to their published source revision", () => {
  window.history.replaceState(null, "", "/");
  const revision = "1234567890abcdef1234567890abcdef12345678";
  vi.stubEnv("VITE_SOURCE_REVISION", revision);
  render(<App />);
  expect(
    screen.getByRole("link", { name: "Source code" }).getAttribute("href"),
  ).toBe(`https://github.com/MithrilAddons/web/tree/${revision}`);
  expect(
    screen.getByRole("link", { name: "AGPL-3.0" }).getAttribute("href"),
  ).toBe(`https://github.com/MithrilAddons/web/blob/${revision}/LICENSE`);
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

it("asks signed-out visitors to link before browsing parties", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockImplementation((url: string) =>
      Promise.resolve(
        url.endsWith("/party/state")
          ? new Response(JSON.stringify({ detail: "Sign in first" }), {
              status: 401,
            })
          : new Response(
              JSON.stringify(
                url.endsWith("/health") ? fixture : { authenticated: false },
              ),
            ),
      ),
    ),
  );
  render(<App />);
  expect(
    screen.getByRole("heading", { name: "Dungeon party finder" }),
  ).toBeTruthy();
  expect(await screen.findByText("Service online")).toBeTruthy();
  expect(
    await screen.findByText(
      "Link your Minecraft account to browse and join parties.",
    ),
  ).toBeTruthy();
  expect(screen.getByRole("region", { name: "Parties" })).toBeTruthy();
  expect(screen.getByRole("heading", { name: "Your account" })).toBeTruthy();
  expect(
    screen
      .getByRole("link", { name: "Party finder" })
      .getAttribute("aria-current"),
  ).toBe("page");
  expect(screen.queryByRole("button", { name: "Start looking" })).toBeNull();
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

it.each(["/", "/party-finder", "/link", "/cookies", "/not-a-page"])(
  "offers source and license links on %s",
  (path) => {
    window.history.replaceState(null, "", path);
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation(() => new Promise(() => {})),
    );
    render(<App />);
    expect(
      screen.getByRole("link", { name: "Source code" }).getAttribute("href"),
    ).toBe("https://github.com/MithrilAddons/web");
    expect(
      screen.getByRole("link", { name: "AGPL-3.0" }).getAttribute("href"),
    ).toBe("https://github.com/MithrilAddons/web/blob/main/LICENSE");
  },
);

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
