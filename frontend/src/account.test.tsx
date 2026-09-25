import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { StrictMode } from "react";
import { afterEach, expect, it, vi } from "vitest";
import { Account, CookiePolicy, LinkAccount } from "./account";

const user = { uuid: "0123456789abcdef0123456789abcdef", name: "TestPlayer" };
const token = "a".repeat(43);
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

it("requires confirmation and an explicit choice to remember the browser", async () => {
  const fetcher = vi
    .fn()
    .mockImplementation((url: string) =>
      Promise.resolve(
        new Response(
          JSON.stringify(
            url.endsWith("preview") ? user : { authenticated: true, user },
          ),
        ),
      ),
    );
  vi.stubGlobal("fetch", fetcher);
  render(
    <StrictMode>
      <LinkAccount token={token} />
    </StrictMode>,
  );
  const button = await screen.findByRole("button", {
    name: "Continue as TestPlayer",
  });
  expect(fetcher.mock.calls.every(([url]) => url.endsWith("preview"))).toBe(
    true,
  );
  const checkbox = screen.getByRole("checkbox") as HTMLInputElement;
  expect(checkbox.checked).toBe(false);
  fireEvent.click(checkbox);
  fireEvent.click(button);
  expect(await screen.findByText("Signed in as TestPlayer.")).toBeTruthy();
  const options = fetcher.mock.calls.find(([url]) =>
    url.endsWith("complete"),
  )?.[1];
  expect(JSON.parse(options.body)).toEqual({ token, remember: true });
  expect(options.credentials).toBe("same-origin");
  expect(localStorage.length).toBe(0);
});

it("does not request malformed links", () => {
  const fetcher = vi.fn();
  vi.stubGlobal("fetch", fetcher);
  render(<LinkAccount token="invalid" />);
  expect(screen.getByText(/create a new link/)).toBeTruthy();
  expect(fetcher).not.toHaveBeenCalled();
});

it("explains expired links without exposing response details", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(new Response("private", { status: 410 })),
  );
  render(<LinkAccount token={token} />);
  expect(await screen.findByRole("alert")).toBeTruthy();
  expect(screen.queryByText("private")).toBeNull();
  expect(screen.queryByRole("button")).toBeNull();
});

it("failed confirmation does not claim success", async () => {
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockImplementation((url: string) =>
        Promise.resolve(
          url.endsWith("preview")
            ? new Response(JSON.stringify(user))
            : new Response("", { status: 410 }),
        ),
      ),
  );
  render(<LinkAccount token={token} />);
  fireEvent.click(
    await screen.findByRole("button", { name: "Continue as TestPlayer" }),
  );
  expect(await screen.findByRole("alert")).toBeTruthy();
  expect(screen.queryByText("Signed in as TestPlayer.")).toBeNull();
});

it("logs out the browser session", async () => {
  const fetcher = vi
    .fn()
    .mockImplementation((url: string) =>
      Promise.resolve(
        new Response(
          JSON.stringify(
            url.endsWith("session")
              ? { authenticated: true, user }
              : { authenticated: false },
          ),
        ),
      ),
    );
  vi.stubGlobal("fetch", fetcher);
  render(<Account />);
  fireEvent.click(await screen.findByRole("button", { name: "Log out" }));
  await waitFor(() =>
    expect(screen.queryByRole("button", { name: "Log out" })).toBeNull(),
  );
  expect(
    fetcher.mock.calls.find(([url]) => url.endsWith("logout"))?.[1].method,
  ).toBe("POST");
});

it("policy names the actual cookie, duration and removal method without a network request", () => {
  const fetcher = vi.fn();
  vi.stubGlobal("fetch", fetcher);
  render(<CookiePolicy />);
  expect(screen.getByText("__Host-mithril_session")).toBeTruthy();
  expect(screen.getByText(/24 hours/)).toBeTruthy();
  expect(screen.getByText(/30 days/)).toBeTruthy();
  expect(screen.getByText(/Use Log out/)).toBeTruthy();
  expect(fetcher).not.toHaveBeenCalled();
});
