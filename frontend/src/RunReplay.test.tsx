import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
} from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import fixture from "../../contracts/run-replay-v1.json";
import { RunReplay as Replay } from "./RunReplay";
import { useState } from "react";
import { decodeReplay, type ReplayPoint } from "./runReplayData";
const points = decodeReplay({ ...fixture, version: 1 });
const following = vi.fn();
function RunReplay({ samples = points }: { samples?: ReplayPoint[] }) {
  const [ms, setMs] = useState(15000);
  const [playing, setPlaying] = useState(false);
  return (
    <Replay
      points={samples}
      rooms={[{ name: "Room", color: "brown" }]}
      visits={[{ room: 0, start: 0, end: 800 }]}
      ms={ms}
      setMs={setMs}
      playing={playing}
      setPlaying={setPlaying}
      onFollow={following}
    >
      <svg role="img" aria-label="Map" />
    </Replay>
  );
}
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  following.mockClear();
});
it("keeps maps without replay usable", () => {
  render(<RunReplay samples={[]} />);
  expect(screen.getByRole("img", { name: "Map" })).toBeTruthy();
  expect(screen.queryByRole("slider")).toBeNull();
});
it("rewinds, plays at default 2x, pauses, changes speed, and stops at the cutoff", () => {
  const frames = vi.fn<(callback: FrameRequestCallback) => number>(() => 1);
  const cancel = vi.fn();
  vi.stubGlobal("requestAnimationFrame", frames);
  vi.stubGlobal("cancelAnimationFrame", cancel);
  vi.spyOn(performance, "now").mockReturnValue(0);
  render(<RunReplay />);
  expect(
    screen.getByRole("button", { name: "2×" }).getAttribute("aria-pressed"),
  ).toBe("true");
  fireEvent.click(screen.getByRole("button", { name: "Play replay" }));
  expect(following).toHaveBeenCalled();
  act(() => frames.mock.calls.at(-1)![0](300));
  expect(screen.getByText("+2 secrets")).toBeTruthy();
  expect(screen.getByText("3 secrets observed")).toBeTruthy();
  expect(screen.getByRole("slider").getAttribute("aria-valuetext")).toBe(
    "0:00.600 of 0:15.000",
  );
  fireEvent.click(screen.getByRole("button", { name: "Pause replay" }));
  expect(cancel).toHaveBeenCalled();
  fireEvent.change(screen.getByRole("slider"), { target: { value: "900" } });
  expect(screen.getByText(/Position not captured/)).toBeTruthy();
  expect(document.querySelector(".replay-player")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "4×" }));
  fireEvent.click(screen.getByRole("button", { name: "Play replay" }));
  act(() => frames.mock.calls.at(-1)![0](1000));
  expect(screen.getByRole("slider").getAttribute("value")).toBe("4900");
  act(() => frames.mock.calls.at(-1)![0](20000));
  expect(screen.getByRole("button", { name: "Play replay" })).toBeTruthy();
  expect(screen.getByRole("slider").getAttribute("value")).toBe("15000");
  expect(screen.queryByText("+2 secrets")).toBeNull();
});
it("supports scoped keyboard navigation, preserving button activation", () => {
  render(<RunReplay />);
  const slider = screen.getByRole("slider");
  fireEvent.click(screen.getByRole("button", { name: "Show route" }));
  expect(document.querySelector(".replay-route")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Show route" }));
  expect(document.querySelector(".replay-route")).toBeNull();
  fireEvent.keyDown(slider, { key: "Home" });
  expect(slider.getAttribute("value")).toBe("0");
  fireEvent.keyDown(slider, { key: "ArrowLeft" });
  expect(slider.getAttribute("value")).toBe("0");
  fireEvent.keyDown(slider, { key: "ArrowRight" });
  expect(slider.getAttribute("value")).toBe("5000");
  fireEvent.keyDown(slider, { key: "End" });
  expect(slider.getAttribute("value")).toBe("15000");
  fireEvent.keyDown(slider, { key: "ArrowRight" });
  expect(slider.getAttribute("value")).toBe("15000");
  fireEvent.keyDown(slider, { key: "Home", ctrlKey: true });
  expect(slider.getAttribute("value")).toBe("15000");
  fireEvent.keyDown(slider, { key: "a" });
  expect(slider.getAttribute("value")).toBe("15000");
  fireEvent.keyDown(screen.getByRole("button", { name: "8×" }), { key: " " });
  expect(screen.getByRole("button", { name: "Play replay" })).toBeTruthy();
  fireEvent.keyDown(slider, { key: " " });
  expect(screen.getByRole("button", { name: "Pause replay" })).toBeTruthy();
  fireEvent.keyDown(slider, { key: " " });
  expect(screen.getByRole("button", { name: "Play replay" })).toBeTruthy();
});
it("draws room segments and pickup ticks; trails never connect teleports or missing samples", () => {
  render(<RunReplay />);
  const slider = screen.getByRole("slider");
  expect(document.querySelectorAll(".run-visit")).toHaveLength(1);
  expect(document.querySelectorAll(".run-secret-tick")).toHaveLength(2);
  fireEvent.change(slider, { target: { value: "600" } });
  const trail = Array.from(document.querySelectorAll(".replay-trail"));
  expect(trail.length).toBeGreaterThan(0);
  // The teleport at 400ms must not join the 200ms position to its destination.
  expect(trail).toHaveLength(2);
  const segments = trail.map((line) =>
    line
      .getAttribute("points")!
      .split(" ")
      .map((pair) => Number(pair.split(",")[0])),
  );
  expect(segments.every(([a, b]) => Math.abs(a! - b!) < 2)).toBe(true);
  fireEvent.change(slider, { target: { value: "900" } });
  expect(document.querySelector(".replay-player")).toBeNull();
  vi.spyOn(slider, "getBoundingClientRect").mockReturnValue({
    left: 0,
    width: 100,
  } as DOMRect);
  fireEvent.pointerMove(slider, { clientX: 1 });
  expect(screen.getByRole("tooltip")).toBeTruthy();
  fireEvent.pointerLeave(slider.parentElement!);
  expect(screen.queryByRole("tooltip")).toBeNull();
});
