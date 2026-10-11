import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { Capture } from "./Capture";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const code = { id: "d".repeat(64), created: 1800000000, last_used: null };

function serve(account: { status?: number; body: unknown }) {
  let codes = [code];
  const fetcher = vi.fn(async (url: string) => {
    const path = url.replace("/api/v1/capture/", "");
    if (path === "codes")
      return new Response(JSON.stringify({ version: 1, code: "x".repeat(43) }));
    if (path === "codes/revoke") {
      codes = [];
      return new Response(JSON.stringify({ version: 1 }));
    }
    if (account.status && account.status !== 200)
      return new Response(JSON.stringify(account.body), {
        status: account.status,
      });
    return new Response(JSON.stringify({ ...(account.body as object), codes }));
  });
  vi.stubGlobal("fetch", fetcher);
  return fetcher;
}

it("creates a code once and lists codes to revoke", async () => {
  const writeText = vi.fn(() => Promise.resolve());
  vi.stubGlobal("navigator", { clipboard: { writeText } });
  const fetcher = serve({ body: { roles: ["capturer"] } });
  render(<Capture />);
  expect(await screen.findByText("Never")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Create upload code" }));
  expect(await screen.findByText("x".repeat(43))).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Copy code" }));
  expect(await screen.findByRole("button", { name: "Copied" })).toBeTruthy();
  expect(writeText).toHaveBeenCalledWith("x".repeat(43));
  fireEvent.click(screen.getByRole("button", { name: "Revoke" }));
  expect(await screen.findByText("No upload codes yet.")).toBeTruthy();
  expect(fetcher).toHaveBeenCalledWith(
    "/api/v1/capture/codes/revoke",
    expect.objectContaining({
      body: JSON.stringify({ version: 1, id: code.id }),
    }),
  );
});

it("explains a missing role, a missing sign-in and errors", async () => {
  serve({ body: { roles: [] } });
  const first = render(<Capture />);
  expect(
    await screen.findByText(/You don’t have the Capturer role yet/),
  ).toBeTruthy();
  first.unmount();
  serve({ status: 401, body: { detail: "Sign in" } });
  const second = render(<Capture />);
  expect(await screen.findByText("Link your Minecraft account")).toBeTruthy();
  second.unmount();
  serve({ status: 500, body: "nope" });
  render(<Capture />);
  expect(await screen.findByRole("alert")).toHaveProperty(
    "textContent",
    "Something went wrong. Try again.",
  );
});
