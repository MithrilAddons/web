import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { World } from "./locationsApi";
import { WorldMap, fit, frame, toWorld, zoom } from "./WorldMap";

const world: World = {
  version: 1,
  revision: "0123456789abcdef",
  x: -100,
  z: -50,
  width: 400,
  height: 200,
  islands: [{ key: "hub", name: "Hub", box: [-100, -50, 300, 150] }],
  image: "/world.png",
};

beforeEach(() => {
  vi.stubGlobal(
    "ResizeObserver",
    class {
      observe() {}
      disconnect() {}
    },
  );
  for (const [name, value] of [
    ["clientWidth", 200],
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
  for (const name of ["clientWidth", "clientHeight"])
    delete (HTMLElement.prototype as unknown as Record<string, unknown>)[name];
});

it("fits, zooms around a point and converts clicks to blocks", () => {
  const fitted = fit(world, 200, 200);
  expect(fitted).toEqual({ scale: 0.5, x: 0, y: 50 });
  expect(toWorld(world, fitted, [100, 100])).toEqual([100, 50]);
  const closer = zoom(fitted, 2, [100, 100], 0.5);
  expect(closer).toEqual({ scale: 1, x: -100, y: 0 });
  // The point under the cursor stays put.
  expect(toWorld(world, closer, [100, 100])).toEqual([100, 50]);
  expect(zoom(fitted, 0.1, [0, 0], 0.5).scale).toBe(0.5);
  expect(zoom(fitted, 100, [0, 0], 0.5).scale).toBe(8);
  const both = frame(
    world,
    [
      [0, 0],
      [100, 0],
    ],
    200,
    200,
  );
  expect(toWorld(world, both, [100, 100])).toEqual([50, 0]);
  expect(frame(world, [[0, 0]], 200, 200).scale).toBeCloseTo(200 / 120);
  expect(frame(world, [[0, 0]], 2000, 2000).scale).toBe(2);
});

function box() {
  return screen.getByRole("img", { name: "Map of every island" })
    .parentElement!;
}

it("places the pin with a click but not a drag, and zooms with the wheel", () => {
  const onPin = vi.fn();
  render(<WorldMap world={world} pin={null} onPin={onPin} />);
  const map = box();
  const image = screen.getByRole("img", { name: "Map of every island" });
  expect(image.style.width).toBe("200px");
  fireEvent.pointerDown(map, { clientX: 100, clientY: 100, pointerId: 1 });
  fireEvent.pointerUp(map, { clientX: 100, clientY: 100, pointerId: 1 });
  expect(onPin).toHaveBeenCalledWith([100, 50]);
  fireEvent.pointerDown(map, { clientX: 100, clientY: 100, pointerId: 1 });
  fireEvent.pointerMove(map, { clientX: 130, clientY: 100, pointerId: 1 });
  fireEvent.pointerUp(map, { clientX: 130, clientY: 100, pointerId: 1 });
  expect(onPin).toHaveBeenCalledTimes(1);
  expect(image.style.transform).toBe("translate(30px, 50px)");
  fireEvent.wheel(map, { deltaY: -100, clientX: 0, clientY: 0 });
  expect(image.style.width).toBe("250px");
  fireEvent.wheel(map, { deltaY: 100, clientX: 0, clientY: 0 });
  expect(image.style.width).toBe("200px");
});

it("pinches to zoom with two fingers", () => {
  const onPin = vi.fn();
  render(<WorldMap world={world} pin={null} onPin={onPin} />);
  const map = box();
  const image = screen.getByRole("img", { name: "Map of every island" });
  fireEvent.pointerDown(map, { clientX: 50, clientY: 100, pointerId: 1 });
  fireEvent.pointerDown(map, { clientX: 150, clientY: 100, pointerId: 2 });
  fireEvent.pointerMove(map, { clientX: 0, clientY: 100, pointerId: 1 });
  fireEvent.pointerUp(map, { clientX: 0, clientY: 100, pointerId: 1 });
  fireEvent.pointerUp(map, { clientX: 150, clientY: 100, pointerId: 2 });
  expect(image.style.width).toBe("300px");
  expect(onPin).not.toHaveBeenCalled();
});

it("shows the guess, the real spot and the line between them", () => {
  const { container } = render(
    <WorldMap world={world} pin={[0, 0]} answer={[100, 0]} />,
  );
  expect(screen.getByTitle("Your guess")).toBeTruthy();
  expect(screen.getByTitle("The real spot")).toBeTruthy();
  expect(container.querySelector("line")).toBeTruthy();
  expect(box().dataset.pinning).toBeUndefined();
});
