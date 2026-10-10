import { cleanup, fireEvent, render, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { SkinAvatar } from "./SkinAvatar";

const image = "data:image/png;base64,AAAA";
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

it("reuses the 3D preview image without another request and layers the hat", () => {
  const fetcher = vi.fn();
  vi.stubGlobal("fetch", fetcher);
  const view = render(
    <SkinAvatar name="Player" image={image} className="avatar" />,
  );
  expect(view.container.querySelector(".skin-face")?.getAttribute("src")).toBe(
    image,
  );
  expect(view.container.querySelector(".skin-hat")?.getAttribute("src")).toBe(
    image,
  );
  expect(fetcher).not.toHaveBeenCalled();
  fireEvent.error(view.container.querySelector("img")!);
  expect(view.container.textContent).toBe("P");
  expect(view.container.querySelector("img")).toBeNull();
});

it("shares one same-origin lookup across repeated chat messages", async () => {
  const fetcher = vi
    .fn()
    .mockResolvedValue(
      new Response(JSON.stringify({ image, model: "default" })),
    );
  vi.stubGlobal("fetch", fetcher);
  const avatar = (
    <SkinAvatar name="Player" uuid={"a".repeat(32)} className="chat-avatar" />
  );
  const view = render(
    <>
      {avatar}
      {avatar}
    </>,
  );
  await waitFor(() =>
    expect(view.container.querySelectorAll("img")).toHaveLength(4),
  );
  expect(fetcher).toHaveBeenCalledExactlyOnceWith(
    `/api/v1/party/skin/${"a".repeat(32)}`,
    expect.objectContaining({ credentials: "same-origin", cache: "no-store" }),
  );
});

it("rejects invalid identities and untrusted image URLs", async () => {
  const fetcher = vi
    .fn()
    .mockResolvedValue(
      new Response(JSON.stringify({ image: "https://untrusted.invalid/face" })),
    );
  vi.stubGlobal("fetch", fetcher);
  const view = render(
    <SkinAvatar name="Player" uuid="../invalid" className="chat-avatar" />,
  );
  expect(view.container.textContent).toBe("P");
  expect(fetcher).not.toHaveBeenCalled();
  view.rerender(
    <SkinAvatar name="Other" uuid={"b".repeat(32)} className="chat-avatar" />,
  );
  await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(1));
  expect(view.container.querySelector("img")).toBeNull();
});

it("does not show an old player's face after the identity changes", async () => {
  let resolve!: (value: Response) => void;
  vi.stubGlobal(
    "fetch",
    vi.fn(
      () =>
        new Promise<Response>((done) => {
          resolve = done;
        }),
    ),
  );
  const view = render(
    <SkinAvatar name="Old" uuid={"c".repeat(32)} className="chat-avatar" />,
  );
  await waitFor(() => expect(resolve).toBeTypeOf("function"));
  view.rerender(
    <SkinAvatar name="New" uuid="invalid" className="chat-avatar" />,
  );
  resolve(new Response(JSON.stringify({ image, model: "default" })));
  await waitFor(() => expect(view.container.textContent).toBe("N"));
  expect(view.container.querySelector("img")).toBeNull();
});
