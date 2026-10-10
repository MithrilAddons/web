import { describe, expect, it } from "vitest";
import contract from "../../contracts/curator-v1.json";
import {
  amount,
  arrowText,
  cell,
  countdown,
  exact,
  full,
  hint,
  known,
  share,
  suggestions,
  words,
  type CatalogItem,
  type Guess,
  type Values,
} from "./curatorFormat";

const guesses = contract.solved.guesses as Guess[];

const base: Values = {
  rarity: "LEGENDARY",
  type: "SWORD",
  museum: "DUNGEONEERING",
  stage: null,
  requirements: {},
  soulbound: null,
  origin: null,
  market: null,
  npc: null,
  length: 11,
};

function guess(
  values: Partial<Values>,
  feedback: Partial<Guess["feedback"]>,
): Guess {
  const none = { match: "none" as const };
  return {
    item: "X",
    name: "X",
    family: false,
    values: { ...base, ...values },
    feedback: {
      rarity: none,
      type: none,
      museum: none,
      stage: none,
      requirements: none,
      soulbound: none,
      origin: none,
      market: none,
      npc: none,
      length: none,
      ...feedback,
    },
  };
}

describe("cells", () => {
  it("shortens values the way the mod does", () => {
    expect(cell("rarity", base)).toBe("LEG");
    expect(cell("rarity", { ...base, rarity: "SUPREME" })).toBe("DIV");
    expect(cell("rarity", { ...base, rarity: null })).toBe("—");
    expect(cell("type", { ...base, type: "DEPLOYABLE" })).toBe("Deploy");
    expect(cell("museum", base)).toBe("Dung.");
    expect(cell("stage", { ...base, stage: "EXPERT" })).toBe("Exp.");
    expect(cell("soulbound", base)).toBe("No");
    expect(cell("soulbound", { ...base, soulbound: "COOP" })).toBe("Co-op");
    expect(cell("soulbound", { ...base, soulbound: "SOLO" })).toBe("Solo");
    expect(cell("origin", base)).toBe("—");
    expect(cell("origin", { ...base, origin: "RIFT" })).toBe("Rift");
    expect(cell("market", base)).toBe("—");
    expect(cell("market", { ...base, market: 6_100_000 })).toBe("6.1M");
    expect(cell("npc", { ...base, npc: 28_000 })).toBe("28k");
    expect(cell("length", base)).toBe("11");
  });

  it("picks the most recognisable requirement and marks more", () => {
    expect(cell("requirements", base)).toBe("—");
    const requirements = {
      "SLAYER:ZOMBIE": 5,
      "DUNGEON_SKILL:": 26,
      "SKILL:COMBAT": 22,
    };
    expect(cell("requirements", { ...base, requirements })).toBe("Cmb 22+");
    const short = (key: string, level: number | null = null) =>
      cell("requirements", { ...base, requirements: { [key]: level } });
    expect(short("DUNGEON_SKILL", 26)).toBe("Cata 26");
    expect(short("DUNGEON_TIER", 3)).toBe("Floor 3");
    expect(short("SLAYER:WOLF", 4)).toBe("Sven 4");
    expect(short("SLAYER:GHOST", 4)).toBe("Slay 4");
    expect(short("HEART_OF_THE_MOUNTAIN", 7)).toBe("HotM 7");
    expect(short("GARDEN_LEVEL", 2)).toBe("Gdn 2");
    expect(short("COLLECTION:WHEAT")).toBe("Coll");
    expect(short("CRIMSON_ISLE_REPUTATION")).toBe("Rep");
    expect(short("KUUDRA_COMPLETION")).toBe("Kuudra");
    expect(short("SKILL:DUNGEONEERING", 1)).toBe("Dung 1");
    expect(short("TARGET_PRACTICE")).toBe("Targe");
  });

  it("spells values out in full for tooltips", () => {
    const requirements = { "SKILL:COMBAT": 22, "SLAYER:WOLF": 4, MISC: null };
    expect(full("requirements", { ...base, requirements })).toBe(
      "Combat 22, Wolf Slayer 4, Misc",
    );
    expect(
      full("requirements", {
        ...base,
        requirements: {
          DUNGEON_SKILL: 1,
          DUNGEON_TIER: 2,
          HEART_OF_THE_MOUNTAIN: 3,
        },
      }),
    ).toBe("Catacombs 1, Floor 2, HotM 3");
    expect(full("requirements", base)).toBe("None");
    expect(full("soulbound", base)).toBe("No");
    expect(full("soulbound", { ...base, soulbound: "COOP" })).toBe("Co-op");
    expect(full("soulbound", { ...base, soulbound: "SOLO" })).toBe("Solo");
    expect(full("market", base)).toBe("Not tradeable");
    expect(full("market", { ...base, market: 5_400_000 })).toBe("5,400,000");
    expect(full("npc", { ...base, npc: 12.5 })).toBe("12.5");
    expect(full("npc", base)).toBe("None");
    expect(full("museum", { ...base, museum: null })).toBe("Not in museum");
    expect(full("museum", base)).toBe("Dungeoneering");
    expect(full("rarity", base)).toBe("Legendary");
    expect(full("stage", base)).toBe("None");
    expect(full("length", base)).toBe("11");
  });

  it("formats amounts with one decimal below a hundred of a unit", () => {
    expect(amount(950)).toBe("950");
    expect(amount(9.5)).toBe("9.5");
    expect(amount(17_440)).toBe("17.4k");
    expect(amount(140_000)).toBe("140k");
    expect(amount(2_000_000_000)).toBe("2B");
    expect(words("VERY_SPECIAL")).toBe("Very Special");
  });

  it("explains each colour and arrow", () => {
    expect(arrowText({ match: "none", arrow: "up" })).toBe("↑");
    expect(arrowText({ match: "none", arrow: "down" })).toBe("↓");
    expect(arrowText({ match: "exact" })).toBe("");
    expect(hint("market", { match: "none", arrow: "up" })).toBe(
      "The answer is worth more",
    );
    expect(hint("length", { match: "none", arrow: "down" })).toBe(
      "The answer's name is shorter",
    );
    expect(hint("type", { match: "none", arrow: "up" })).toBe("");
    expect(hint("type", { match: "none", arrow: "down" })).toBe("");
    expect(hint("type", { match: "exact" })).toBe("Matches the answer");
    expect(hint("soulbound", { match: "partial" })).toBe(
      "Both soulbound, but not the same way",
    );
    expect(hint("requirements", { match: "partial" })).toBe(
      "Some requirements match the answer's",
    );
    expect(hint("type", { match: "none" })).toBe("Doesn't match the answer");
  });
});

describe("search", () => {
  const items: CatalogItem[] = [
    ["ASPECT_OF_THE_VOID", "Aspect of the Void"],
    ["ASPECT_OF_THE_END", "Aspect of the End"],
    ["SPIRIT_SCEPTRE", "Spirit Sceptre"],
    ["AOTD", "Aspect of the Dragons"],
    ["WAND", "Wand of Atonement"],
    ["SHEEP", "Bat Person (Spirit)"],
  ];

  it("ranks name starts before word starts, then shorter names", () => {
    expect(suggestions(items, " asp", new Set()).map(([id]) => id)).toEqual([
      "ASPECT_OF_THE_END",
      "ASPECT_OF_THE_VOID",
      "AOTD",
    ]);
    expect(suggestions(items, "spirit", new Set()).map(([id]) => id)).toEqual([
      "SPIRIT_SCEPTRE",
      "SHEEP",
    ]);
    expect(
      suggestions(items, "asp", new Set(["ASPECT_OF_THE_END"]), 1),
    ).toEqual([["ASPECT_OF_THE_VOID", "Aspect of the Void"]]);
    expect(suggestions(items, "  ", new Set())).toEqual([]);
    expect(exact(items, " wand OF atonement ")).toEqual([
      "WAND",
      "Wand of Atonement",
    ]);
    expect(exact(items, "wand")).toBeUndefined();
  });
});

describe("results", () => {
  it("shares the same squares as the mod", () => {
    expect(share(1, guesses, true, 10)).toBe(
      ["Curator #1 2/10", "🟩🟩🟩⬛🟩🟩🟩⬛⬛🟩", "🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩"].join(
        "\n",
      ),
    );
    expect(share(3, [], false, 10)).toBe("Curator #3 X/10");
  });

  it("sums up what every guess said", () => {
    const seen = [
      guess(
        { rarity: "RARE", market: 6_100_000, length: 12, stage: "EXPERT" },
        {
          rarity: { match: "none", arrow: "up" },
          market: { match: "none", arrow: "up" },
          length: { match: "none", arrow: "up" },
          stage: { match: "none", arrow: "down" },
          soulbound: { match: "partial" },
        },
      ),
      guess(
        { rarity: "MYTHIC", market: 18_000_000, length: 16, npc: 28_000 },
        {
          rarity: { match: "none", arrow: "down" },
          market: { match: "none", arrow: "down" },
          length: { match: "none", arrow: "down" },
          npc: { match: "exact" },
          type: { match: "exact" },
        },
      ),
    ];
    expect(known(seen, "rarity")).toEqual({
      text: "above Rare, below Mythic",
      state: "range",
    });
    expect(known(seen, "stage")).toEqual({
      text: "below Expert",
      state: "range",
    });
    expect(known(seen, "market")).toEqual({
      text: "6.1M – 18M",
      state: "range",
    });
    expect(known(seen, "length")).toEqual({ text: "12 – 16", state: "range" });
    expect(known(seen, "npc")).toEqual({ text: "28k", state: "exact" });
    expect(known(seen, "type")).toEqual({ text: "Sword", state: "exact" });
    expect(known(seen, "soulbound")).toEqual({ text: "No", state: "partial" });
    expect(known(seen, "origin")).toEqual({ text: "—", state: "unknown" });
    expect(known(seen.slice(0, 1), "market")).toEqual({
      text: "over 6.1M",
      state: "range",
    });
    expect(
      known(
        [
          guess(
            { rarity: "SUPREME" },
            { rarity: { match: "none", arrow: "up" } },
          ),
        ],
        "rarity",
      ),
    ).toEqual({ text: "above Divine", state: "range" });
    expect(
      known(
        [guess({ rarity: "ODD" }, { rarity: { match: "none", arrow: "up" } })],
        "rarity",
      ),
    ).toEqual({ text: "—", state: "unknown" });
  });

  it("counts down in hours and minutes, never below a minute", () => {
    expect(countdown(3 * 3_600_000 + 11.5 * 60_000)).toBe("3h 12m");
    expect(countdown(5 * 60_000)).toBe("5m");
    expect(countdown(-1)).toBe("1m");
  });
});
