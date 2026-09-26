import { expect, it } from "vitest";
import contract from "../../contracts/party-v1.json";
import {
  errorMessage,
  failures,
  formatMetric,
  formatRule,
  type PartyState,
  parseMetric,
  PartyRequestError,
  requirements,
  type Rules,
} from "./partyApi";

const state = contract.state as unknown as PartyState;

it("combines shared and class rules like the server, stricter first", () => {
  const rules: Rules = {
    shared: { catacombs: 48, magical_power: 1300 },
    per_class: { healer: { catacombs: 52, class_level: 45 } },
    exempt: ["tank"],
  };
  expect(requirements(rules, "healer")).toEqual([
    ["catacombs", 52],
    ["class_level", 45],
    ["magical_power", 1300],
  ]);
  expect(requirements(rules, "tank")).toEqual([["magical_power", 1300]]);
});

it("computes eligibility from the viewer's own stats in the shared contract", () => {
  const party = contract.detail as unknown as { rules: Rules };
  expect(failures(party.rules, "healer", state.you.stats, "M7")).toEqual([]);
  const strict: Rules = { shared: { ss_ms: 14000 }, per_class: {}, exempt: [] };
  // SS is not reported yet: a missing value never passes a rule.
  expect(failures(strict, "tank", state.you.stats, "M7")).toEqual([
    { metric: "ss_ms", threshold: 14000, value: null },
  ]);
});

it("formats and parses each unit", () => {
  expect(formatMetric("catacombs", 51.9)).toBe("51");
  expect(formatMetric("class_level", 53.25)).toBe("53");
  expect(formatMetric("magical_power", 1380)).toBe("1,380");
  expect(formatMetric("s_plus_ms", 331000)).toBe("5:31");
  expect(formatMetric("ss_ms", 12600)).toBe("12.6s");
  expect(formatMetric("solo_ms", null)).toBe("—");
  expect(formatRule("magical_power", 1300)).toBe("≥1,300");
  expect(formatRule("s_plus_ms", 360000)).toBe("≤6:00");
  expect(parseMetric("s_plus_ms", "5:40")).toBe(340000);
  expect(parseMetric("ss_ms", "14.0")).toBe(14000);
  expect(parseMetric("magical_power", "1,300")).toBe(1300);
  expect(parseMetric("catacombs", "")).toBeNull();
  expect(parseMetric("s_plus_ms", "5:99")).toBeUndefined();
  expect(parseMetric("ss_ms", "21")).toBeUndefined();
  expect(parseMetric("class_level", "51")).toBeUndefined();
});

it("turns refusal codes into readable messages", () => {
  expect(errorMessage(new PartyRequestError(409, "slot_taken"))).toBe(
    "Someone else took that slot.",
  );
  expect(
    errorMessage(new PartyRequestError(422, "unknown_names", ["ghost"])),
  ).toBe("No Minecraft player named ghost.");
  expect(errorMessage(new Error("network"))).toMatch(/unavailable/);
});
