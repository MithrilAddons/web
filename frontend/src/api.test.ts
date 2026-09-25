import { afterEach, describe, expect, it, vi } from "vitest";
import fixture from "../../contracts/health-v1.json";
import { getHealth } from "./api";

afterEach(() => vi.unstubAllGlobals());

describe("health contract", () => {
  it("accepts the shared API fixture and forwards cancellation", async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValue(new Response(JSON.stringify(fixture)));
    vi.stubGlobal("fetch", fetcher);
    const signal = new AbortController().signal;
    expect(await getHealth(signal)).toEqual(fixture);
    expect(fetcher).toHaveBeenCalledWith("/api/v1/health", {
      signal,
      cache: "no-store",
    });
  });
  it.each([
    null,
    {},
    { ...fixture, api_version: 2 },
    { ...fixture, status: "failed" },
  ])("rejects malformed or incompatible data: %j", async (body) => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response(JSON.stringify(body))),
    );
    await expect(getHealth(new AbortController().signal)).rejects.toThrow();
  });
  it("rejects HTTP errors", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response("", { status: 503 })),
    );
    await expect(getHealth(new AbortController().signal)).rejects.toThrow(
      "Service unavailable",
    );
  });
});
