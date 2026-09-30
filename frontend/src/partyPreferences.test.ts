import { beforeEach, afterEach, expect, it, vi } from "vitest";
import {
  loadPartyRules,
  savePartyRules,
  resetPartyRules,
} from "./partyPreferences";
import type { Rules } from "./partyApi";

const rules: Rules = {
  shared: { catacombs: 45 },
  per_class: { healer: { solo_ms: 60000 } },
  exempt: ["tank"],
};
beforeEach(() => localStorage.clear());
afterEach(() => vi.restoreAllMocks());

it("isolates accounts and floors, and resets only the selected floor", () => {
  savePartyRules("a", "M7", rules);
  savePartyRules("a", "F7", { ...rules, shared: { catacombs: 30 } });
  expect(loadPartyRules("a", "M7")).toEqual(rules);
  expect(loadPartyRules("a", "F7").shared.catacombs).toBe(30);
  expect(loadPartyRules("b", "M7").shared).toEqual({});
  resetPartyRules("a", "M7");
  expect(loadPartyRules("a", "M7").shared).toEqual({});
  expect(loadPartyRules("a", "F7").shared.catacombs).toBe(30);
});

it.each([
  "broken",
  "null",
  JSON.stringify({ version: 2, rules }),
  JSON.stringify({
    version: 1,
    rules: { ...rules, shared: { catacombs: 1001 } },
  }),
  JSON.stringify({ version: 1, rules: { ...rules, shared: { catacombs: 0 } } }),
  JSON.stringify({ version: 1, rules: { ...rules, shared: { unknown: 10 } } }),
  JSON.stringify({
    version: 1,
    rules: { ...rules, per_class: { warrior: {} } },
  }),
  JSON.stringify({ version: 1, rules: { ...rules, exempt: ["warrior"] } }),
])("rejects corrupt, unsupported and out-of-range preferences: %s", (value) => {
  localStorage.setItem("mithril.party-rules.v1:a:M7", value);
  expect(loadPartyRules("a", "M7")).toEqual({
    shared: {},
    per_class: {},
    exempt: [],
  });
});

it("keeps the editor usable when browser storage is blocked", () => {
  vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
    throw new Error("blocked");
  });
  vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
    throw new Error("blocked");
  });
  vi.spyOn(Storage.prototype, "removeItem").mockImplementation(() => {
    throw new Error("blocked");
  });
  expect(loadPartyRules("a", "M7").shared).toEqual({});
  expect(savePartyRules("a", "M7", rules)).toBe(false);
  expect(resetPartyRules("a", "M7")).toBe(false);
});
