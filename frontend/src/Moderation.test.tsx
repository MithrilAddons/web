import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { Moderation } from "./Moderation";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
const uuid = "c".repeat(32);
const record = {
  id: "r".repeat(43),
  floor: "F7",
  kind: "solo_clear",
  real_ms: 100000,
  ticks: 2000,
  source: "legacy",
  status: "eligible",
};
function server(role = "owner") {
  const fetcher = vi.fn(async (url: string, options?: RequestInit) => {
    const path = url.replace("/api/v1/moderation/", "");
    let body: object = {};
    if (!options?.body) {
      if (path === "access")
        body = { role, moderators: [], network_bans_available: true };
      if (path.startsWith("resolve/")) body = { uuid, name: "SyntheticPlayer" };
      if (path.startsWith("player/"))
        body = { uuid, records: [record], cases: [] };
      if (path === "audit") body = { entries: [] };
    }
    return new Response(JSON.stringify(body), { status: 200 });
  });
  vi.stubGlobal("fetch", fetcher);
  return fetcher;
}

async function find() {
  fireEvent.change(await screen.findByLabelText("Player"), {
    target: { value: "SyntheticPlayer" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Find player" }));
  await screen.findByText("SyntheticPlayer");
}

it("denies access without displaying moderator controls", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(
      async () =>
        new Response(JSON.stringify({ detail: "Moderator access required" }), {
          status: 403,
        }),
    ),
  );
  render(<Moderation />);
  expect((await screen.findByRole("alert")).textContent).toContain(
    "Moderator access required",
  );
  expect(screen.queryByLabelText("Player")).toBeNull();
});

it("requires a reason and sends the reviewed state with a correction", async () => {
  const fetcher = server();
  render(<Moderation />);
  await find();
  expect(
    (
      screen.getByRole("button", {
        name: "Save correction",
      }) as HTMLButtonElement
    ).disabled,
  ).toBe(true);
  fireEvent.change(screen.getByLabelText("Reason"), {
    target: { value: "Corrected from run evidence" },
  });
  fireEvent.change(screen.getByLabelText("Time (ms)"), {
    target: { value: "150000" },
  });
  fireEvent.change(screen.getByLabelText("Ticks"), {
    target: { value: "3000" },
  });
  fireEvent.submit(screen.getByLabelText("Time (ms)").closest("form")!);
  await waitFor(() =>
    expect(fetcher).toHaveBeenCalledWith(
      "/api/v1/moderation/record",
      expect.objectContaining({
        body: JSON.stringify({
          version: 1,
          record_id: record.id,
          expected_status: "eligible",
          action: "correct",
          real_ms: 150000,
          ticks: 3000,
          reason: "Corrected from run evidence",
        }),
      }),
    ),
  );
});

it("hides grants from moderators and identifies shared-IP effects", async () => {
  server("moderator");
  render(<Moderation />);
  await find();
  expect(screen.queryByRole("button", { name: "Grant moderator" })).toBeNull();
  fireEvent.change(screen.getByLabelText("Action"), {
    target: { value: "network_ban" },
  });
  expect(
    screen.getByText("Also blocks other accounts using the same IP address."),
  ).toBeTruthy();
});

it("does not silently retry a failed write and retains the reason", async () => {
  const fetcher = server();
  render(<Moderation />);
  await find();
  fireEvent.change(screen.getByLabelText("Reason"), {
    target: { value: "Review" },
  });
  fetcher.mockResolvedValueOnce(
    new Response(
      JSON.stringify({ detail: "Record changed; reload before editing" }),
      { status: 409 },
    ),
  );
  fireEvent.click(screen.getByRole("button", { name: "Invalidate" }));
  expect((await screen.findByRole("alert")).textContent).toContain(
    "Record changed",
  );
  expect((screen.getByLabelText("Reason") as HTMLTextAreaElement).value).toBe(
    "Review",
  );
  expect(
    fetcher.mock.calls.filter(([url]) => url.endsWith("/record")),
  ).toHaveLength(1);
});
