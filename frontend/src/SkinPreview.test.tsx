import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { SkinPreview } from "./SkinPreview";

const mocks = vi.hoisted(() => ({
  construct: vi.fn(),
  dispose: vi.fn(),
  render: vi.fn(),
  load: vi.fn(),
  add: vi.fn(),
  remove: vi.fn(),
  resize: vi.fn(),
  disconnect: vi.fn(),
  reset: vi.fn(),
  model: { rotation: { x: 0, y: 0 } },
}));
vi.mock("skinview3d", () => ({
  SkinViewer: class {
    constructor(options: unknown) {
      mocks.construct(options);
    }
    controls = {
      addEventListener: mocks.add,
      removeEventListener: mocks.remove,
      update: vi.fn(),
    };
    playerObject = mocks.model;
    loadSkin = mocks.load;
    resetSkin = vi.fn();
    dispose = mocks.dispose;
    render = mocks.render;
    setSize = mocks.resize;
    resetCameraPose = mocks.reset;
    zoom = 0.8;
    composer = { dispose: vi.fn() };
    renderer = { forceContextLoss: vi.fn() };
  },
}));

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});
function setup() {
  mocks.load.mockResolvedValue(undefined);
  vi.stubGlobal(
    "ResizeObserver",
    class {
      observe() {}
      disconnect = mocks.disconnect;
    },
  );
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          image: "data:image/png;base64,AAAA",
          model: "slim",
        }),
      ),
    ),
  );
}

it("loads only same-origin skin data, pauses rendering, supports reset and disposes on unmount", async () => {
  setup();
  const view = render(<SkinPreview name="TestPlayer" />);
  await waitFor(() => expect(screen.getByRole("img").tabIndex).toBe(0));
  expect(screen.queryByText(/Drag to rotate/)).toBeNull();
  expect(screen.queryByRole("button")).toBeNull();
  expect(fetch).toHaveBeenCalledWith(
    "/api/v1/auth/skin",
    expect.objectContaining({ credentials: "same-origin" }),
  );
  expect(mocks.construct).toHaveBeenCalledWith(
    expect.objectContaining({ renderPaused: true, height: 250 }),
  );
  expect(mocks.load).toHaveBeenCalledWith("data:image/png;base64,AAAA", {
    model: "slim",
  });
  const initial = mocks.model.rotation.y;
  fireEvent.keyDown(screen.getByRole("img"), { key: "ArrowRight" });
  expect(mocks.model.rotation.y).toBeGreaterThan(initial);
  fireEvent.keyDown(screen.getByRole("img"), { key: "Home" });
  expect(mocks.reset).toHaveBeenCalled();
  view.unmount();
  expect(mocks.dispose).toHaveBeenCalledTimes(1);
  expect(mocks.disconnect).toHaveBeenCalled();
});

it("does not construct a renderer after an unmount while fetching", async () => {
  setup();
  let resolve!: (response: Response) => void;
  vi.stubGlobal(
    "fetch",
    vi.fn().mockReturnValue(
      new Promise<Response>((done) => {
        resolve = done;
      }),
    ),
  );
  const view = render(<SkinPreview name="TestPlayer" />);
  view.unmount();
  resolve(
    new Response(
      JSON.stringify({ image: "data:image/png;base64,AAAA", model: "default" }),
    ),
  );
  await waitFor(() => expect(mocks.construct).not.toHaveBeenCalled());
});

it("shows a fallback on skin failure without constructing WebGL", async () => {
  setup();
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(new Response("", { status: 503 })),
  );
  render(<SkinPreview name="TestPlayer" />);
  expect(await screen.findByText("Skin preview unavailable.")).toBeTruthy();
  expect(mocks.construct).not.toHaveBeenCalled();
});

it("rejects remote URLs instead of making third-party browser requests", async () => {
  setup();
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          image: "https://evil.invalid/a.png",
          model: "slim",
        }),
      ),
    ),
  );
  render(<SkinPreview name="TestPlayer" />);
  expect(await screen.findByText("Skin preview unavailable.")).toBeTruthy();
  expect(mocks.construct).not.toHaveBeenCalled();
});

it("handles unavailable WebGL without breaking the account panel", async () => {
  setup();
  mocks.construct.mockImplementationOnce(() => {
    throw new Error("WebGL unavailable");
  });
  render(<SkinPreview name="TestPlayer" />);
  expect(await screen.findByText("Skin preview unavailable.")).toBeTruthy();
});
