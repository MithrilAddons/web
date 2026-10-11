import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { CUBE_ORDER, Panorama, look, sliceFaces } from "./Panorama";

const mocks = vi.hoisted(() => ({
  render: vi.fn(),
  setSize: vi.fn(),
  dispose: vi.fn(),
  textureDispose: vi.fn(),
  rotation: vi.fn(),
  cube: vi.fn(),
  disconnect: vi.fn(),
  context: {
    translate: vi.fn(),
    rotate: vi.fn(),
    drawImage: vi.fn(),
  },
}));

vi.mock("three", () => ({
  SRGBColorSpace: "srgb",
  WebGLRenderer: class {
    domElement = document.createElement("canvas");
    setPixelRatio = vi.fn();
    setSize = mocks.setSize;
    render = mocks.render;
    dispose = mocks.dispose;
  },
  PerspectiveCamera: class {
    aspect = 1;
    rotation = { order: "", set: mocks.rotation };
    updateProjectionMatrix = vi.fn();
  },
  Scene: class {
    background: unknown = null;
  },
  CubeTexture: class {
    colorSpace = "";
    needsUpdate = false;
    constructor(images: unknown[]) {
      mocks.cube(images);
    }
    dispose = mocks.textureDispose;
  },
}));

let decode: () => Promise<void>;

beforeEach(() => {
  decode = () => Promise.resolve();
  vi.stubGlobal(
    "ResizeObserver",
    class {
      observe() {}
      disconnect = mocks.disconnect;
    },
  );
  Object.defineProperty(HTMLImageElement.prototype, "decode", {
    configurable: true,
    value: () => decode(),
  });
  Object.defineProperty(HTMLImageElement.prototype, "naturalWidth", {
    configurable: true,
    get: () => 30,
  });
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(
    mocks.context as unknown as CanvasRenderingContext2D,
  );
  for (const [name, value] of [
    ["clientWidth", 400],
    ["clientHeight", 200],
  ] as const)
    Object.defineProperty(HTMLElement.prototype, name, {
      configurable: true,
      get: () => value,
    });
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  vi.clearAllMocks();
  for (const name of ["clientWidth", "clientHeight"])
    delete (HTMLElement.prototype as unknown as Record<string, unknown>)[name];
});

it("turns drags into a view that stops short of straight up and down", () => {
  expect(look({ yaw: 0, pitch: 0 }, 100, 0)).toEqual({ yaw: 0.5, pitch: 0 });
  const up = look({ yaw: 0, pitch: 0 }, 0, 10_000);
  expect(up.pitch).toBeCloseTo(Math.PI / 2 - 0.01);
  expect(look({ yaw: 0, pitch: 0 }, 0, -10_000).pitch).toBeCloseTo(
    -(Math.PI / 2 - 0.01),
  );
});

it("cuts the round image into six faces, turning up and down round", () => {
  const image = document.createElement("img");
  const faces = sliceFaces(image);
  expect(faces).toHaveLength(6);
  expect(faces[0]!.width).toBe(10);
  expect(mocks.context.drawImage).toHaveBeenNthCalledWith(
    5,
    image,
    10,
    10,
    10,
    10,
    0,
    0,
    10,
    10,
  );
  // Only the up (4) and down (5) faces are turned.
  expect(mocks.context.rotate).toHaveBeenCalledTimes(2);
  expect(mocks.context.translate).toHaveBeenCalledWith(10, 10);
});

it("shows the panorama, reports it ready and turns with a drag", async () => {
  const onReady = vi.fn();
  const view = render(<Panorama src="/round.webp" onReady={onReady} />);
  await waitFor(() => expect(onReady).toHaveBeenCalledTimes(1));
  const host = screen.getByRole("figure", { name: /Drag to look around/ });
  const canvas = host.querySelector("canvas")!;
  expect(mocks.setSize).toHaveBeenCalledWith(400, 200, false);
  // Minecraft's right face fills three.js's -x slot, and so on.
  const images = mocks.cube.mock.calls[0]![0] as HTMLCanvasElement[];
  expect(images).toHaveLength(6);
  expect(CUBE_ORDER).toEqual([3, 1, 4, 5, 2, 0]);
  const before = mocks.rotation.mock.calls.at(-1)!;
  fireEvent.pointerDown(canvas, { clientX: 100, clientY: 100, pointerId: 1 });
  fireEvent.pointerMove(canvas, { clientX: 140, clientY: 90, pointerId: 1 });
  fireEvent.pointerUp(canvas, { pointerId: 1 });
  fireEvent.pointerMove(canvas, { clientX: 300, clientY: 90, pointerId: 1 });
  const after = mocks.rotation.mock.calls.at(-1)!;
  expect(after[1]).toBeCloseTo((before[1] as number) + 0.2);
  expect(after[0]).toBeCloseTo(-0.05);
  view.unmount();
  expect(mocks.dispose).toHaveBeenCalled();
  expect(mocks.textureDispose).toHaveBeenCalled();
  expect(mocks.disconnect).toHaveBeenCalled();
});

it("says so when the image can't be loaded", async () => {
  decode = () => Promise.reject(new Error("broken"));
  const onReady = vi.fn();
  render(<Panorama src="/broken.webp" onReady={onReady} />);
  expect(await screen.findByRole("alert")).toHaveProperty(
    "textContent",
    "The panorama couldn’t be loaded.",
  );
  expect(onReady).not.toHaveBeenCalled();
});
