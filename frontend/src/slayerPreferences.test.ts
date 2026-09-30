import { afterEach, expect, it, vi } from "vitest";
import { slayers } from "./slayerCalculator";
import {
  defaultSlayerSettings,
  loadSlayerSettings,
  saveSlayerSettings,
  loadSelectedSlayer,
  saveSelectedSlayer,
} from "./slayerPreferences";

const slayer = slayers[0]!;
const key = "mithril.slayer-profits.v1:" + slayer.displayName;
afterEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
});

it.each(["", "-1", "10001", "Infinity", "not a number"])(
  "preserves the last valid settings during an invalid Magic Find edit: %s",
  (magicFind) => {
    const saved = {
      ...defaultSlayerSettings(slayer),
      magicFind: "350",
      bosses: "80",
    };
    saveSlayerSettings(slayer, saved);
    saveSlayerSettings(slayer, { ...saved, magicFind });
    expect(loadSlayerSettings(slayer)).toEqual(saved);
  },
);

it("preserves settings during a blank bosses edit and accepts zero", () => {
  const saved = { ...defaultSlayerSettings(slayer), bosses: "0" };
  saveSlayerSettings(slayer, saved);
  saveSlayerSettings(slayer, { ...saved, bosses: "" });
  expect(loadSlayerSettings(slayer)).toEqual(saved);
});

it.each(["broken json", "null", "[]", "false"])(
  "ignores malformed saved settings: %s",
  (raw) => {
    localStorage.setItem(key, raw);
    expect(loadSlayerSettings(slayer)).toEqual(defaultSlayerSettings(slayer));
  },
);

it("ignores unsupported settings while retaining valid fields", () => {
  localStorage.setItem(
    key,
    JSON.stringify({
      tierNumber: 99,
      meter: "Removed drop",
      magicFind: -1,
      bosses: "100001",
      mode: "removed",
      halfPrice: "true",
      extraSlots: true,
    }),
  );
  expect(loadSlayerSettings(slayer)).toEqual({
    ...defaultSlayerSettings(slayer),
    extraSlots: true,
  });
  localStorage.setItem(
    key,
    JSON.stringify({ tierNumber: 1, meter: "Warden Heart" }),
  );
  expect(loadSlayerSettings(slayer)).toMatchObject({
    tierNumber: 1,
    meter: "",
  });
});

it("defaults to the first Slayer when the saved selection is unknown", () => {
  localStorage.setItem("mithril.slayer-profits.v1:selected", "Removed Slayer");
  expect(loadSelectedSlayer()).toBe(0);
});

it("keeps defaults usable when browser storage is blocked", () => {
  vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
    throw new Error("blocked");
  });
  vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
    throw new Error("blocked");
  });
  expect(loadSlayerSettings(slayer)).toEqual(defaultSlayerSettings(slayer));
  expect(loadSelectedSlayer()).toBe(0);
  expect(() =>
    saveSlayerSettings(slayer, defaultSlayerSettings(slayer)),
  ).not.toThrow();
  expect(() => saveSelectedSlayer(slayer)).not.toThrow();
});
