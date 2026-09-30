import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { AccountPrivacy, PrivacyPolicy } from "./Privacy";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

it("shows the configured operator and a usable privacy contact", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(
      async () =>
        new Response(
          JSON.stringify({
            operator: "Synthetic Operator",
            email: "privacy@example.invalid",
          }),
        ),
    ),
  );
  render(<PrivacyPolicy />);
  const link = await screen.findByRole("link", {
    name: "privacy@example.invalid",
  });
  expect(link.getAttribute("href")).toBe("mailto:privacy@example.invalid");
  expect(screen.getByText(/Synthetic Operator/)).toBeTruthy();
});

it("keeps deletion unavailable after a failed session check", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response("", { status: 503 })),
  );
  render(<AccountPrivacy />);
  expect((await screen.findByRole("alert")).textContent).toContain(
    "Could not check your account",
  );
  expect(screen.queryByRole("button")).toBeNull();
});

it("requires explicit confirmation and clears it when deletion scope changes", async () => {
  const fetcher = vi.fn(
    async () =>
      new Response(
        JSON.stringify({
          authenticated: true,
          user: { uuid: "c".repeat(32), name: "Synthetic" },
          devices: [],
        }),
      ),
  );
  vi.stubGlobal("fetch", fetcher);
  render(<AccountPrivacy />);
  await screen.findByText("Delete data for Synthetic");
  const button = screen.getByRole("button", {
    name: "Delete synced PBs",
  }) as HTMLButtonElement;
  expect(button.disabled).toBe(true);
  fireEvent.change(screen.getByLabelText("Type DELETE to confirm"), {
    target: { value: "DELETE" },
  });
  expect(button.disabled).toBe(false);
  fireEvent.change(screen.getByLabelText("Delete"), {
    target: { value: "account" },
  });
  expect(button.disabled).toBe(true);
  fireEvent.change(screen.getByLabelText("Type DELETE to confirm"), {
    target: { value: "DELETE" },
  });
  fireEvent.click(button);
  expect(
    await screen.findByText("Account deleted. You are signed out."),
  ).toBeTruthy();
  expect(fetcher).toHaveBeenCalledWith(
    "/api/v1/auth/erase",
    expect.objectContaining({
      method: "POST",
      body: JSON.stringify({
        version: 1,
        scope: "account",
        confirmation: "DELETE",
      }),
    }),
  );
});

it("does not show deletion controls when signed out", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response(JSON.stringify({ authenticated: false }))),
  );
  render(<AccountPrivacy />);
  expect(
    await screen.findByRole("link", {
      name: "Sign in with your Minecraft account",
    }),
  ).toBeTruthy();
  expect(screen.queryByRole("button")).toBeNull();
});

it("does not automatically retry an uncertain deletion", async () => {
  const fetcher = vi.fn(async (url: string) => {
    if (url.endsWith("erase")) throw new Error("Connection lost");
    return new Response(
      JSON.stringify({
        authenticated: true,
        user: { name: "Synthetic", uuid: "c".repeat(32) },
        devices: [],
      }),
    );
  });
  vi.stubGlobal("fetch", fetcher);
  render(<AccountPrivacy />);
  fireEvent.change(await screen.findByLabelText("Type DELETE to confirm"), {
    target: { value: "DELETE" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Delete synced PBs" }));
  expect(await screen.findByRole("alert")).toBeTruthy();
  await waitFor(() =>
    expect(
      fetcher.mock.calls.filter(([url]) => url.endsWith("erase")),
    ).toHaveLength(1),
  );
});
