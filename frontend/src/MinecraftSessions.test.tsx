import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { MinecraftSessions } from "./MinecraftSessions";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

it("revokes only the selected Minecraft session and keeps browser authentication", async () => {
  const devices = [
    { id: "a".repeat(64), name: "Synthetic", expires: 2000000000 },
  ];
  const fetcher = vi.fn((_url: string, options?: RequestInit) =>
    Promise.resolve(
      new Response(
        JSON.stringify(
          options?.method === "POST" ? { revoked: true } : { devices },
        ),
      ),
    ),
  );
  vi.stubGlobal("fetch", fetcher);
  render(<MinecraftSessions />);
  fireEvent.click(
    await screen.findByRole("button", { name: "Sign out Minecraft session 1" }),
  );
  expect(await screen.findByText("No Minecraft sessions.")).toBeTruthy();
  const options = fetcher.mock.calls[1]?.[1];
  expect(fetcher.mock.calls[1]?.[0]).toBe("/api/v1/auth/devices/revoke");
  expect(JSON.parse(options?.body as string)).toEqual({ id: "a".repeat(64) });
  expect(options?.credentials).toBe("same-origin");
});

it("keeps a session visible when revocation fails", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn((_url: string, options?: RequestInit) =>
      Promise.resolve(
        options?.method === "POST"
          ? new Response("", { status: 503 })
          : new Response(
              JSON.stringify({
                devices: [
                  {
                    id: "b".repeat(64),
                    name: "Synthetic",
                    expires: 2000000000,
                  },
                ],
              }),
            ),
      ),
    ),
  );
  render(<MinecraftSessions />);
  fireEvent.click(
    await screen.findByRole("button", { name: "Sign out Minecraft session 1" }),
  );
  expect(await screen.findByRole("alert")).toHaveProperty(
    "textContent",
    "Could not revoke this session. Try again.",
  );
  await waitFor(() =>
    expect(
      (
        screen.getByRole("button", {
          name: "Sign out Minecraft session 1",
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(false),
  );
});
