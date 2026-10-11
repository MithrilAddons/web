import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { DuelBoard } from "./LocationBoard";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function serve(status: number, body: unknown) {
  vi.stubGlobal(
    "fetch",
    vi.fn(() =>
      Promise.resolve(new Response(JSON.stringify(body), { status })),
    ),
  );
}

const row = (rank: number, name: string, you = false) => ({
  rank,
  name,
  rating: 2000 - rank * 10,
  wins: 5,
  losses: 2,
  draws: 1,
  peak: 2010,
  you,
});

it("ranks the season, pins your row and keeps past seasons", async () => {
  serve(200, {
    version: 1,
    season: "2026-10",
    players: 12,
    top: [row(1, "Alice"), row(2, "Bob")],
    you: row(12, "Carol", true),
    past: [
      { season: "2026-09", top: [{ rank: 1, name: "Dave", rating: 2100 }] },
    ],
  });
  render(<DuelBoard />);
  expect(await screen.findByText("October 2026 season")).toBeTruthy();
  expect(screen.getByText("Alice")).toBeTruthy();
  const mine = screen.getByText("Carol").closest("tr")!;
  expect(mine.getAttribute("aria-current")).toBe("true");
  expect(screen.getAllByText("5–2–1")).toHaveLength(3);
  fireEvent.click(screen.getByText("September 2026"));
  expect(screen.getByText("Dave · 2100")).toBeTruthy();
});

it("says when nobody is established yet, and reports errors", async () => {
  serve(200, {
    version: 1,
    season: "2026-10",
    players: 0,
    top: [],
    you: null,
    past: [],
  });
  const first = render(<DuelBoard />);
  expect(
    await screen.findByText(
      "Nobody has an established rating this season yet.",
    ),
  ).toBeTruthy();
  first.unmount();
  serve(500, { detail: "Try later" });
  render(<DuelBoard />);
  expect(await screen.findByRole("alert")).toHaveProperty(
    "textContent",
    "Try later",
  );
});
