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
function server(role = "owner", data: Record<string, object> = {}) {
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
      body = data[path] ?? body;
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

it.each(["7", "permanent"])(
  "submits a %s restriction with selected evidence",
  async (duration) => {
    const fetcher = server();
    render(<Moderation />);
    await find();
    const checkbox = screen.getByRole("checkbox");
    fireEvent.click(checkbox);
    fireEvent.click(checkbox);
    fireEvent.click(checkbox);
    fireEvent.change(screen.getByLabelText("Reason"), {
      target: { value: "Confirmed abuse" },
    });
    fireEvent.change(screen.getByLabelText("Duration"), {
      target: { value: duration },
    });
    fireEvent.click(screen.getByRole("button", { name: "Apply restriction" }));
    await screen.findByText("Saved.");
    const options = fetcher.mock.calls.find(([url]) =>
      url.endsWith("/sanction"),
    )![1]!;
    expect(JSON.parse(options.body as string)).toEqual({
      version: 1,
      uuid,
      kind: "ban",
      expires: duration === "permanent" ? null : expect.any(Number),
      record_ids: [record.id],
      report_ids: [],
      reason: "Confirmed abuse",
    });
  },
);

it.each([false, true])(
  "uses the current appeal state when changing a case (%s)",
  async (open) => {
    const item = {
      id: "case",
      kind: "ban",
      expires: null,
      revoked: null,
      appeal_open: Number(open),
      reason: "Case reason",
    };
    const fetcher = server("owner", {
      [`player/${uuid}`]: { uuid, records: [], cases: [item] },
    });
    render(<Moderation />);
    await find();
    expect(screen.getByText("No records.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Case evidence" }));
    await screen.findByText("Record evidence");
    fireEvent.change(screen.getByLabelText("Reason"), {
      target: { value: "Appeal reviewed" },
    });
    fireEvent.click(
      screen.getByRole("button", {
        name: open ? "Close appeal" : "Open appeal",
      }),
    );
    await screen.findByText("Saved.");
    expect(fetcher).toHaveBeenCalledWith(
      "/api/v1/moderation/case",
      expect.objectContaining({
        body: JSON.stringify({
          version: 1,
          case_id: "case",
          action: open ? "close_appeal" : "open_appeal",
          reason: "Appeal reviewed",
        }),
      }),
    );
  },
);

it("allows the owner to revoke moderator access and paginate attributed audit actions", async () => {
  const entry = {
    id: 9,
    at: 1000,
    actor: "a".repeat(32),
    subject: uuid,
    action: "grant",
    reason: "Access review",
    before_json: "false",
    after_json: "true",
  };
  const fetcher = server("owner", {
    access: {
      role: "owner",
      moderators: [uuid],
      network_bans_available: false,
    },
    audit: { entries: [entry] },
    "audit?before=9": { entries: [] },
  });
  render(<Moderation />);
  await find();
  fireEvent.change(screen.getByLabelText("Reason"), {
    target: { value: "Role no longer needed" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Revoke moderator" }));
  await screen.findByText("Access review");
  expect(fetcher).toHaveBeenCalledWith(
    "/api/v1/moderation/access",
    expect.objectContaining({
      body: JSON.stringify({
        version: 1,
        uuid,
        enabled: false,
        reason: "Role no longer needed",
      }),
    }),
  );
  fireEvent.click(screen.getByRole("button", { name: "Older actions" }));
  await screen.findByText("No older actions.");
  fireEvent.click(screen.getByRole("button", { name: "Refresh audit" }));
  await waitFor(() =>
    expect(
      fetcher.mock.calls.filter(([url]) => url.endsWith("/audit")),
    ).toHaveLength(2),
  );
});

it.each(["Remove message", "Dismiss report"])(
  "reviews reported text and sends %s with a reason",
  async (action) => {
    const report = {
      id: "report",
      uuid,
      reporter: "d".repeat(32),
      reason: "Harassment",
      evidence: JSON.stringify({ text: "Synthetic message" }),
    };
    const fetcher = server("moderator", { chat: { reports: [report] } });
    render(<Moderation />);
    fireEvent.click(
      await screen.findByRole("button", { name: "Refresh reports" }),
    );
    await screen.findByText("Harassment");
    fireEvent.click(screen.getByRole("button", { name: "Review player" }));
    await screen.findByLabelText("Reason");
    fireEvent.change(screen.getByLabelText("Review reason"), {
      target: { value: "Message reviewed" },
    });
    fireEvent.click(screen.getByRole("button", { name: action }));
    await waitFor(() =>
      expect(fetcher).toHaveBeenCalledWith(
        "/api/v1/moderation/chat",
        expect.objectContaining({
          body: JSON.stringify({
            version: 1,
            report_id: "report",
            action: action === "Remove message" ? "hide" : "dismiss",
            reason: "Message reviewed",
          }),
        }),
      ),
    );
  },
);

it("reports a failed chat review without retrying the mutation", async () => {
  const fetcher = server();
  render(<Moderation />);
  await screen.findByLabelText("Player");
  fetcher.mockRejectedValueOnce(new Error("Reports unavailable"));
  fireEvent.click(screen.getByRole("button", { name: "Refresh reports" }));
  expect((await screen.findByRole("alert")).textContent).toContain(
    "Reports unavailable",
  );
  expect(
    fetcher.mock.calls.filter(([url]) => url.endsWith("/chat")),
  ).toHaveLength(1);
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
