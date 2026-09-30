// Ported from Mithril64/mithriladdons at 403f0dd (owner-authorized web adaptation).
import catalogue from "../../backend/mithril_web/slayer_data.json";

export type Drop = {
  name: string;
  bazaarId: string | null;
  pool: string;
  weight: number;
  minAmount: number;
  maxAmount: number;
  auctionName: string;
  rollsPerBoss: number;
  separateMagicFindBonus: number | null;
  npcSellPrice: number | null;
};
export type Tier = {
  number: number;
  questCost: number;
  slayerXp: number;
  spawnCombatXp: number;
  drops: Drop[];
};
export type Slayer = { displayName: string; tiers: Tier[] };
export const slayers: Slayer[] = catalogue;
export type Quote = {
  price: number;
  source: string;
  samples: number;
  spread: number;
};
export type PetQuote = {
  name: string;
  rarity: string;
  startLevel: number;
  endLevel: number;
  startPrice: number;
  endPrice: number;
  requiredXp: number;
  samples: number;
};
export type Feed = {
  status: "loading" | "ready" | "stale" | "unavailable";
  updated: number | null;
};
export type Market = {
  version: 1;
  bazaar: Record<string, { instant: number; offer: number }>;
  npc: Record<string, number>;
  auctions: Record<string, Quote>;
  pets: PetQuote[];
  feeds: { bazaar: Feed; npc: Feed; auctions: Feed; sales: Feed };
};
export type Prices = Record<string, { price: number; source: string }>;
export const eligible = (drop: Drop) =>
  drop.pool === "MAIN" || drop.pool === "EXTRA";
export const amount = (drop: Drop) => (drop.minAmount + drop.maxAmount) / 2;

export function bestPrices(
  tier: Tier,
  market: Pick<Market, "bazaar" | "npc" | "auctions"> | null,
  mode: "instant" | "offer",
): Prices {
  return Object.fromEntries(
    tier.drops.flatMap((drop) => {
      const bazaar = drop.bazaarId
        ? market?.bazaar[drop.bazaarId]?.[mode]
        : undefined;
      const auction = market?.auctions[drop.auctionName];
      const npc = Math.max(
        drop.npcSellPrice ?? 0,
        ...[drop.bazaarId, drop.name, drop.auctionName].map((key) =>
          key ? (market?.npc[key] ?? 0) : 0,
        ),
      );
      const candidates = [
        {
          price: bazaar ?? 0,
          source:
            mode === "instant" ? "Bazaar instant sell" : "Bazaar sell offer",
        },
        { price: auction?.price ?? 0, source: auction?.source ?? "BIN" },
        { price: npc, source: "NPC" },
      ]
        .filter(({ price }) => Number.isFinite(price) && price > 0)
        .sort((a, b) => b.price - a.price);
      return candidates[0] ? [[drop.name, candidates[0]]] : [];
    }),
  );
}

export function probabilities(
  tier: Tier,
  magicFind: number,
  meter: string | null,
  progress = 0,
): number[] {
  const selected = tier.drops.findIndex((d) => d.name === meter && eligible(d));
  const weights = tier.drops.map(
    (d, i) =>
      d.weight *
      (i === selected ? 1 + 2 * Math.min(1, Math.max(0, progress)) : 1),
  );
  const sum = (pool: string, values: number[]) =>
    tier.drops.reduce(
      (total, d, i) => total + (d.pool === pool ? values[i]! : 0),
      0,
    );
  const rawMain = sum("MAIN", weights),
    rawExtra = sum("EXTRA", weights);
  const adjusted = tier.drops.map((d, i) => {
    if (!eligible(d)) return d.weight;
    const chance =
      weights[i]! / (10000 + rawMain + (d.pool === "EXTRA" ? rawExtra : 0));
    return weights[i]! * (chance < 0.05 ? 1 + magicFind / 100 : 1);
  });
  const main = sum("MAIN", adjusted),
    extra = sum("EXTRA", adjusted);
  return tier.drops.map((d, i) => {
    if (d.pool === "TOKEN") return 1;
    if (d.pool === "SEPARATE")
      return d.separateMagicFindBonus === null
        ? d.weight
        : Math.min(
            1,
            Math.max(
              0,
              d.weight * (1 + (magicFind + d.separateMagicFindBonus) / 100),
            ),
          ) * d.rollsPerBoss;
    if (selected >= 0 && progress >= 1 && tier.drops[selected]!.pool === d.pool)
      return i === selected ? 1 : 0;
    return adjusted[i]! / (10000 + main + (d.pool === "EXTRA" ? extra : 0));
  });
}

export function meterRequirement(slayer: Slayer, meter: string): number {
  const chance = Math.max(
    ...slayer.tiers.map(
      (tier) =>
        probabilities(tier, 0, null)[
          tier.drops.findIndex((d) => d.name === meter)
        ] ?? 0,
    ),
  );
  return chance > 0 ? Math.ceil(500 / chance) : 0;
}

export function rates(
  slayer: Slayer,
  tier: Tier,
  magicFind: number,
  meter: string | null,
  boost: boolean,
): number[] {
  const selected = tier.drops.findIndex((d) => d.name === meter && eligible(d));
  if (tier.number < 3 || selected < 0)
    return probabilities(tier, magicFind, null);
  const requirement = meterRequirement(slayer, meter!);
  const counts = tier.drops.map(() => 0);
  let survival = 1,
    kills = 0,
    xp = 0;
  while (survival > 1e-12) {
    const chances = probabilities(tier, magicFind, meter, xp / requirement);
    kills += survival;
    chances.forEach((chance, i) => {
      counts[i]! += survival * chance;
    });
    survival *= 1 - Math.min(1, chances[selected]!);
    xp += tier.slayerXp * (boost ? 1.1 : 1);
  }
  return counts.map((count) => count / kills);
}

export function calculate(
  slayer: Slayer,
  tier: Tier,
  magicFind: number,
  bosses: number,
  meter: string | null,
  prices: Prices,
  boost: boolean,
) {
  const dropRates = rates(slayer, tier, magicFind, meter, boost);
  const grossFor = (values: number[]) =>
    tier.drops.reduce(
      (total, d, i) =>
        total + values[i]! * amount(d) * bosses * (prices[d.name]?.price ?? 0),
      0,
    );
  const gross = grossFor(dropRates),
    fees = tier.questCost * bosses;
  const target = tier.drops
    .filter(eligible)
    .filter((d) => prices[d.name])
    .sort(
      (a, b) =>
        prices[b.name]!.price * amount(b) - prices[a.name]!.price * amount(a),
    )[0];
  let comparison: {
    itemName: string;
    alwaysSelectedCoinsPerHour: number;
    fillUnselectedCoinsPerHour: number;
  } | null = null;
  if (tier.number >= 3 && target) {
    const fillKills = Math.max(
      1,
      Math.ceil(
        meterRequirement(slayer, target.name) /
          (tier.slayerXp * (boost ? 1.1 : 1)),
      ),
    );
    const base = probabilities(tier, magicFind, null);
    const guarantee = probabilities(tier, magicFind, target.name, 1);
    const unselected = base.map(
      (chance, i) => (chance * fillKills + guarantee[i]!) / (fillKills + 1),
    );
    comparison = {
      itemName: target.name,
      alwaysSelectedCoinsPerHour:
        grossFor(rates(slayer, tier, magicFind, target.name, boost)) - fees,
      fillUnselectedCoinsPerHour: grossFor(unselected) - fees,
    };
  }
  return {
    dropRates,
    gross,
    fees,
    net: gross - fees,
    unpriced: tier.drops.filter((d) => !prices[d.name]).length,
    comparison,
  };
}

export function petLeveling(
  tier: Tier,
  bosses: number,
  quotes: PetQuote[],
  shards: boolean,
) {
  const active =
    tier.spawnCombatXp * bosses * 1.6 * 1.5 * 1.05 * (shards ? 1.1 : 1);
  const shared = active * (0.12 + 0.15 + (shards ? 0.1 : 0));
  const pets = quotes
    .map((quote) => ({
      ...quote,
      coinsPerXp: (quote.endPrice - quote.startPrice) / quote.requiredXp,
    }))
    .filter((q) => q.coinsPerXp > 0 && Number.isFinite(q.coinsPerXp))
    .sort((a, b) => b.coinsPerXp - a.coinsPerXp)
    .slice(0, 3)
    .map((q) => ({ ...q, coinsPerHour: q.coinsPerXp * (active + shared) }));
  return { active, shared, pets, best: pets[0]?.coinsPerHour ?? 0 };
}
