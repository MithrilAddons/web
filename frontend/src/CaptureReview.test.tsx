import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { CaptureReview } from "./CaptureReview";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const base = {
  name: "Alice",
  island: "hub",
  island_name: "Hub",
  status: "submitted",
  reviewer_note: null,
  updated: 1800000000,
  note: "top of the bank",
  captured_at: 1800000000000,
};
const near = { ...base, id: "a".repeat(22), x: 10, y: 72, z: 20 };
const far = { ...base, id: "b".repeat(22), x: 900, y: 72, z: 20, note: "" };
const hubMap = {
  id: "m".repeat(22),
  min_x: -54,
  min_z: -44,
  max_x: 73,
  max_z: 83,
};

function serve(pages: Record<string, unknown>) {
  const fetcher = vi.fn(async (url: string, options?: RequestInit) => {
    const path = url.replace("/api/v1/moderation/", "");
    if (options?.body) {
      const body = JSON.parse(options.body as string) as { note: string };
      if (body.note === "fail")
        return new Response(JSON.stringify({ detail: "Try later" }), {
          status: 500,
        });
      return new Response(JSON.stringify({ version: 1 }));
    }
    const page = pages[path];
    return page
      ? new Response(JSON.stringify(page))
      : new Response(JSON.stringify({ detail: "Reviewer access required" }), {
          status: 403,
        });
  });
  vi.stubGlobal("fetch", fetcher);
  return fetcher;
}

it("shows each location's faces and spot, and decides with a note", async () => {
  const fetcher = serve({
    "captures?kind=locations&status=submitted&offset=0": {
      total: 3,
      items: [near, far],
      current_maps: { hub: hubMap },
    },
    "captures?kind=locations&status=submitted&offset=2": {
      total: 3,
      items: [{ ...near, id: "c".repeat(22), name: null }],
      current_maps: { hub: hubMap },
    },
  });
  render(<CaptureReview />);
  const cards = await screen.findAllByRole("listitem");
  expect(within(cards[0]!).getAllByRole("img")).toHaveLength(7);
  expect(within(cards[0]!).getByAltText("Front face").getAttribute("src")).toBe(
    `/api/v1/moderation/captures/locations/${near.id}/faces/0.png`,
  );
  expect(within(cards[0]!).getByText("“top of the bank”")).toBeTruthy();
  const pin = cards[0]!.querySelector(".capture-pin") as HTMLElement;
  expect(pin.style.left).toBe("50%");
  expect(within(cards[1]!).getByRole("alert").textContent).toContain(
    "outside the island’s current map",
  );
  const send = within(cards[0]!).getByRole("button", {
    name: "Request changes",
  }) as HTMLButtonElement;
  expect(send.disabled).toBe(true);
  fireEvent.change(within(cards[0]!).getByLabelText("Note for the capturer"), {
    target: { value: "a player is visible" },
  });
  fireEvent.click(send);
  expect(await screen.findByText("Sent back.")).toBeTruthy();
  expect(fetcher).toHaveBeenCalledWith(
    "/api/v1/moderation/captures/decide",
    expect.objectContaining({
      body: JSON.stringify({
        version: 1,
        kind: "locations",
        id: near.id,
        decision: "changes",
        note: "a player is visible",
      }),
    }),
  );
  fireEvent.click(screen.getByRole("button", { name: "Load more" }));
  expect(await screen.findByText(/Erased account/)).toBeTruthy();
});

it("approves, rejects and reports failures", async () => {
  serve({
    "captures?kind=locations&status=submitted&offset=0": {
      total: 1,
      items: [near],
      current_maps: {},
    },
  });
  render(<CaptureReview />);
  expect(
    await screen.findByText("No approved map of this island yet."),
  ).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Approve" }));
  expect(await screen.findByText("Approved.")).toBeTruthy();
  fireEvent.change(screen.getByLabelText("Note for the capturer"), {
    target: { value: "fail" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Reject" }));
  expect(await screen.findByRole("alert")).toHaveProperty(
    "textContent",
    "Try later",
  );
  fireEvent.change(screen.getByLabelText("Note for the capturer"), {
    target: { value: "blurry" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Reject" }));
  expect(await screen.findByText("Rejected.")).toBeTruthy();
});

it("compares maps and filters by status", async () => {
  serve({
    "captures?kind=locations&status=submitted&offset=0": {
      total: 0,
      items: [],
      current_maps: {},
    },
    "captures?kind=maps&status=submitted&offset=0": {
      total: 1,
      items: [{ ...base, ...hubMap, id: "n".repeat(22) }],
      current_maps: { hub: hubMap },
    },
    "captures?kind=maps&status=approved&offset=0": {
      total: 1,
      items: [
        { ...base, ...hubMap, status: "approved", reviewer_note: "great" },
      ],
      current_maps: { hub: hubMap },
    },
  });
  render(<CaptureReview />);
  expect(await screen.findByText("Nothing here.")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Maps" }));
  expect(await screen.findByAltText("Current map")).toBeTruthy();
  expect(screen.getByText(/128×128 blocks from \(-54, -44\)/)).toBeTruthy();
  fireEvent.change(screen.getByLabelText("Show"), {
    target: { value: "approved" },
  });
  expect(await screen.findByText("Approved · great")).toBeTruthy();
  expect(screen.queryByAltText("Current map")).toBeNull();
  fireEvent.change(screen.getByLabelText("Show"), {
    target: { value: "rejected" },
  });
  await waitFor(() =>
    expect(screen.getByRole("alert").textContent).toBe(
      "Reviewer access required",
    ),
  );
});

it("retires a live location", async () => {
  const fetcher = serve({
    "captures?kind=locations&status=approved&offset=0": {
      total: 1,
      items: [{ ...near, status: "approved" }],
      current_maps: { hub: hubMap },
    },
    "captures?kind=locations&status=submitted&offset=0": {
      total: 0,
      items: [],
      current_maps: {},
    },
  });
  render(<CaptureReview />);
  await screen.findByText("Nothing here.");
  fireEvent.change(screen.getByLabelText("Show"), {
    target: { value: "approved" },
  });
  expect(await screen.findByText("Live in the game")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Retire" }));
  expect(
    await screen.findByText("Retired: it's out of the game."),
  ).toBeTruthy();
  expect(fetcher).toHaveBeenCalledWith(
    "/api/v1/moderation/captures/decide",
    expect.objectContaining({
      body: JSON.stringify({
        version: 1,
        kind: "locations",
        id: near.id,
        decision: "retire",
        note: "",
      }),
    }),
  );
});
