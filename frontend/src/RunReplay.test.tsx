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
import { useState, type ComponentProps } from "react";

function RunReplay(props: Omit<ComponentProps<typeof Replay>, "ms" | "setMs">) {
  const [ms, setMs] = useState(0);
  return <Replay {...props} ms={ms} setMs={setMs} />;
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

it("keeps maps without replay usable", () => {
  render(
    <RunReplay>
      <svg role="img" aria-label="Map" />
    </RunReplay>,
  );
  expect(screen.getByRole("img", { name: "Map" })).toBeTruthy();
  expect(screen.queryByRole("slider")).toBeNull();
});

it("plays, pauses, seeks, shows secret updates and stops at the cutoff", () => {
  const frames = vi.fn<(callback: FrameRequestCallback) => number>(() => 1);
  const cancel = vi.fn();
  vi.stubGlobal("requestAnimationFrame", frames);
  vi.stubGlobal("cancelAnimationFrame", cancel);
  vi.spyOn(performance, "now").mockReturnValue(0);
  render(
    <RunReplay data={{ ...fixture, version: 1 }}>
      <svg role="img" aria-label="Map" />
    </RunReplay>,
  );
  expect(screen.getByText("0 secrets observed")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Play replay" }));
  act(() => frames.mock.calls.at(-1)![0](600));
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
  fireEvent.change(screen.getByRole("slider"), { target: { value: "1000" } });
  expect(document.querySelector(".replay-player")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Play replay" }));
  act(() => frames.mock.calls.at(-1)![0](20000));
  expect(screen.getByRole("button", { name: "Replay again" })).toBeTruthy();
  expect(screen.getByRole("slider").getAttribute("aria-valuetext")).toBe(
    "0:15.000 of 0:15.000",
  );
  expect(screen.queryByText("+2 secrets")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Replay again" }));
  expect(screen.getByRole("slider").getAttribute("aria-valuetext")).toBe(
    "0:00.000 of 0:15.000",
  );
  expect(screen.getByText(/Secret indicators are approximate/)).toBeTruthy();
});
