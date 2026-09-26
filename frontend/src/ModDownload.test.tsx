import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { ModDownload } from "./ModDownload";
import { PartyWorkspace } from "./PartyFinder";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
const url =
  "https://github.com/MithrilAddons/mithrilpf/releases/download/v1.2.3/mithrilpf-1.2.3.jar";

it("offers the versioned JAR directly when signed out", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn((path: string) =>
      Promise.resolve(
        path.endsWith("party/state")
          ? new Response("{}", { status: 401 })
          : new Response(
              JSON.stringify(
                path.endsWith("mod-release")
                  ? { status: "ready", release: { version: "1.2.3", url } }
                  : { authenticated: false },
              ),
            ),
      ),
    ),
  );
  render(<PartyWorkspace />);
  expect(
    (await screen.findByRole("link", { name: /Download mod/ })).getAttribute(
      "href",
    ),
  ).toBe(url);
  expect(
    screen.getByText("Link your Minecraft account to browse and join parties."),
  ).toBeTruthy();
});

it.each(["none", "unavailable"])(
  "keeps a releases fallback for %s",
  async (status) => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(
          new Response(JSON.stringify({ status, release: null })),
        ),
    );
    render(<ModDownload />);
    await screen.findByText(
      status === "none"
        ? "No public release yet."
        : "Check GitHub for downloads.",
    );
    expect(
      screen.getByRole("link", { name: "View releases" }).getAttribute("href"),
    ).toBe("https://github.com/MithrilAddons/mithrilpf/releases");
    expect(screen.queryByRole("link", { name: /Download mod/ })).toBeNull();
  },
);

it("keeps the fallback if the request fails", async () => {
  vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("Offline")));
  render(<ModDownload />);
  await screen.findByText("Check GitHub for downloads.");
});

it("offers published prereleases and clearly labels the beta", async () => {
  const version = "0.2.0-rc.3";
  const betaUrl = `https://github.com/MithrilAddons/mithrilpf/releases/download/v${version}/mithrilpf-${version}.jar`;
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          status: "ready",
          release: { version, url: betaUrl },
        }),
      ),
    ),
  );
  render(<ModDownload />);
  expect(
    (
      await screen.findByRole("link", { name: /Download mod.*Beta/ })
    ).getAttribute("href"),
  ).toBe(betaUrl);
});

it("rejects a download outside the expected release asset", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          status: "ready",
          release: { version: "1.2.3", url: "https://evil.invalid/mod.jar" },
        }),
      ),
    ),
  );
  render(<ModDownload />);
  await screen.findByText("Check GitHub for downloads.");
  expect(screen.queryByRole("link", { name: /Download mod/ })).toBeNull();
});
