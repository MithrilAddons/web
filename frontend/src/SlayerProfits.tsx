import { useEffect, useMemo, useState } from "react";
import {
  amount,
  bestPrices,
  calculate,
  eligible,
  meterRequirement,
  petLeveling,
  slayers,
  type Market,
  type Prices,
  type Slayer,
  type Tier,
} from "./slayerCalculator";
import "./slayerProfits.css";
import {
  loadSelectedSlayer,
  loadSlayerSettings,
  saveSelectedSlayer,
  saveSlayerSettings,
  type SlayerSettings,
} from "./slayerPreferences";

const number = (value: number, digits = 0) =>
  value.toLocaleString("en-US", { maximumFractionDigits: digits });
const coins = (value: number) =>
  value.toLocaleString("en-US", {
    notation: "compact",
    maximumFractionDigits: 2,
  });
const roman = ["", "I", "II", "III", "IV", "V"];

export function SlayerProfits() {
  const [slayerIndex, setSlayerIndex] = useState(loadSelectedSlayer);
  const [preferences, setPreferences] = useState(() =>
    Object.fromEntries(
      slayers.map((slayer) => [slayer.displayName, loadSlayerSettings(slayer)]),
    ),
  );
  const slayer = slayers[slayerIndex]!;
  const settings = preferences[slayer.displayName]!;
  const {
    tierNumber,
    magicFind,
    bosses,
    meter,
    boost,
    shards,
    aatroxXp,
    halfPrice,
    extraSlots,
    petXpBoost,
    excludeActive,
    mode,
  } = settings;
  const updateSettings = (changes: Partial<SlayerSettings>) =>
    setPreferences((previous) => ({
      ...previous,
      [slayer.displayName]: { ...previous[slayer.displayName]!, ...changes },
    }));
  const setMeter = (meter: string) => updateSettings({ meter });
  useEffect(() => {
    saveSelectedSlayer(slayer);
    saveSlayerSettings(slayer, settings);
  }, [slayer, settings]);
  const { market, error, loading, refreshPrices } = useSlayerMarket();
  const tier =
    slayer.tiers.find((t) => t.number === tierNumber) ?? slayer.tiers[0]!;
  const valid =
    magicFind.trim() !== "" &&
    bosses.trim() !== "" &&
    Number.isFinite(+magicFind) &&
    +magicFind >= 0 &&
    +magicFind <= 10000 &&
    Number.isFinite(+bosses) &&
    +bosses >= 0 &&
    +bosses <= 100000;
  const mf = valid ? +magicFind : 0,
    bph = valid ? +bosses : 0;
  const prices = useMemo(
    () => bestPrices(tier, market, mode),
    [tier, market, mode],
  );
  const result = useMemo(
    () =>
      calculate(slayer, tier, mf, bph, meter || null, prices, {
        meterXpMultiplier: (boost ? 1.1 : 1) * (aatroxXp ? 1.25 : 1),
        halfPrice,
      }),
    [slayer, tier, mf, bph, meter, prices, boost, aatroxXp, halfPrice],
  );
  const pets = useMemo(
    () =>
      petLeveling(tier, bph, market?.pets ?? [], {
        shards,
        extraSlots,
        petXpBoost,
        excludeActive,
      }),
    [tier, bph, market, shards, extraSlots, petXpBoost, excludeActive],
  );

  const feeds = market ? Object.values(market.feeds) : [];
  const waiting =
    !error && (!market || feeds.some((feed) => feed.status === "loading"));
  const stale =
    error ||
    feeds.some(
      (feed) => feed.status === "stale" || feed.status === "unavailable",
    );

  return (
    <div className="slayer-page">
      <title>Slayer profits · Mithril</title>
      <div className="page-heading slayer-heading">
        <h1>Slayer profits</h1>
        <button type="button" onClick={refreshPrices} disabled={loading}>
          {loading ? "Refreshing…" : "Refresh prices"}
        </button>
      </div>

      <section className="slayer-controls" aria-label="Calculator settings">
        <label>
          <span>Slayer</span>
          <select
            value={slayerIndex}
            onChange={(e) => {
              setSlayerIndex(+e.target.value);
            }}
          >
            {slayers.map((s, i) => (
              <option key={s.displayName} value={i}>
                {s.displayName}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>Tier</span>
          <select
            value={tier.number}
            onChange={(e) => {
              updateSettings({ tierNumber: +e.target.value, meter: "" });
            }}
          >
            {slayer.tiers.map((t) => (
              <option key={t.number} value={t.number}>
                Tier {roman[t.number]}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>Magic Find</span>
          <input
            type="number"
            min="0"
            max="10000"
            step="any"
            value={magicFind}
            onChange={(e) => updateSettings({ magicFind: e.target.value })}
          />
        </label>
        <label>
          <span>Bosses/hr</span>
          <input
            type="number"
            min="0"
            max="100000"
            step="any"
            value={bosses}
            onChange={(e) => updateSettings({ bosses: e.target.value })}
          />
        </label>
        <label className="slayer-meter">
          <span>RNG meter</span>
          <select
            value={meter}
            disabled={tier.number < 3}
            onChange={(e) => setMeter(e.target.value)}
          >
            <option value="">No item selected</option>
            {tier.drops.filter(eligible).map((d) => (
              <option key={d.name}>{d.name}</option>
            ))}
          </select>
        </label>
        <label>
          <span>Bazaar pricing</span>
          <select
            value={mode}
            onChange={(e) =>
              updateSettings({ mode: e.target.value as "instant" | "offer" })
            }
          >
            <option value="instant">Instant sell</option>
            <option value="offer">Sell offer</option>
          </select>
        </label>
        <details className="slayer-boosts">
          <summary>
            Boosts &amp; pet options ·{" "}
            {
              [
                boost,
                shards,
                aatroxXp,
                halfPrice,
                extraSlots,
                petXpBoost,
                excludeActive,
              ].filter(Boolean).length
            }{" "}
            active
          </summary>
          <div className="slayer-options">
            <fieldset>
              <legend>Aatrox</legend>
              <label>
                <input
                  type="checkbox"
                  checked={aatroxXp}
                  onChange={(e) =>
                    updateSettings({ aatroxXp: e.target.checked })
                  }
                />{" "}
                +25% RNG meter XP
              </label>
              <label>
                <input
                  type="checkbox"
                  checked={halfPrice}
                  onChange={(e) =>
                    updateSettings({ halfPrice: e.target.checked })
                  }
                />{" "}
                Half-price quests
              </label>
            </fieldset>
            <fieldset>
              <legend>Diana</legend>
              <label>
                <input
                  type="checkbox"
                  checked={extraSlots}
                  onChange={(e) =>
                    updateSettings({ extraSlots: e.target.checked })
                  }
                />{" "}
                3 EXP Share slots (+10% rate)
              </label>
              <label>
                <input
                  type="checkbox"
                  checked={petXpBoost}
                  onChange={(e) =>
                    updateSettings({ petXpBoost: e.target.checked })
                  }
                />{" "}
                +35% pet XP
              </label>
            </fieldset>
            <fieldset>
              <legend>Options</legend>
              <label>
                <input
                  type="checkbox"
                  checked={boost}
                  onChange={(e) => updateSettings({ boost: e.target.checked })}
                />{" "}
                +10% RNG meter XP
              </label>
              <label>
                <input
                  type="checkbox"
                  checked={shards}
                  onChange={(e) => updateSettings({ shards: e.target.checked })}
                />{" "}
                Pet shard bonuses
              </label>
              <label>
                <input
                  type="checkbox"
                  checked={excludeActive}
                  onChange={(e) =>
                    updateSettings({ excludeActive: e.target.checked })
                  }
                />{" "}
                Exclude main pet
              </label>
            </fieldset>
          </div>
        </details>
      </section>
      {!valid && (
        <p role="alert" className="slayer-warning">
          Enter Magic Find from 0 to 10,000 and bosses/hr from 0 to 100,000.
        </p>
      )}

      <div className="slayer-price-status">
        <MarketStatus
          waiting={waiting}
          stale={stale}
          unpriced={result.unpriced}
        />
        {market && (
          <p className="quiet-label">
            Bazaar updated{" "}
            {market.feeds.bazaar.updated
              ? new Date(market.feeds.bazaar.updated * 1000).toLocaleTimeString(
                  [],
                  { hour: "2-digit", minute: "2-digit" },
                )
              : "not yet"}{" "}
            · Auction House updated{" "}
            {market.feeds.auctions.updated
              ? new Date(
                  market.feeds.auctions.updated * 1000,
                ).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
              : "not yet"}
          </p>
        )}
      </div>
      <ProfitMetrics
        result={result}
        pets={pets}
        valid={valid && market !== null && result.unpriced < tier.drops.length}
        bph={bph}
        questCost={tier.questCost * (halfPrice ? 0.5 : 1)}
        waiting={waiting}
        stale={stale}
      />

      <div className="slayer-bottom-grid">
        <section className="slayer-panel" aria-labelledby="strategy-title">
          <h2 id="strategy-title">RNG strategy</h2>
          <RngStrategy
            tierNumber={tier.number}
            comparison={result.comparison}
            valid={valid}
            meter={meter}
            onSelect={setMeter}
          />
        </section>
        <PetPanel pets={pets} excludeActive={excludeActive} />
      </div>

      <details className="slayer-assumptions">
        <summary>Drop breakdown</summary>{" "}
        <DropBreakdown
          slayer={slayer}
          tier={tier}
          prices={prices}
          dropRates={result.dropRates}
          bph={bph}
          meter={meter}
          valid={valid}
        />
      </details>
      <CalculationDetails market={market} />
    </div>
  );
}

function Metric({
  label,
  value,
  detail,
  state,
}: Readonly<{
  label: string;
  value: string;
  detail?: string;
  state?: string;
}>) {
  return (
    <div className="slayer-metric" data-state={state}>
      <h2>{label}</h2>
      <strong>{value}</strong>
      {detail && <p>{detail}</p>}
    </div>
  );
}

function DropBreakdown({
  slayer,
  tier,
  prices,
  dropRates,
  bph,
  meter,
  valid,
}: Readonly<{
  slayer: Slayer;
  tier: Tier;
  prices: Prices;
  dropRates: number[];
  bph: number;
  meter: string;
  valid: boolean;
}>) {
  return (
    <section className="slayer-drops" aria-labelledby="drops-title">
      <div className="slayer-section-heading">
        <h2 id="drops-title">Drop breakdown</h2>
        <span>
          {slayer.displayName} {roman[tier.number]}
        </span>
      </div>
      {/* Keyboard focus lets users scroll the wide table with arrow keys. */}
      <section
        className="slayer-table-scroll"
        tabIndex={0}
        aria-label="Drop prices and expected rates"
      >
        <table>
          <thead>
            <tr>
              <th scope="col">Drop</th>
              <th scope="col">Drop rate</th>
              <th scope="col">Items/hr</th>
              <th scope="col">Unit price</th>
              <th scope="col">Coins/hr</th>
            </tr>
          </thead>
          <tbody>
            {tier.drops.map((drop, i) => {
              const price = prices[drop.name];
              const rate = dropRates[i]!;
              const items = rate * amount(drop) * bph;
              return (
                <tr key={drop.name} data-selected={drop.name === meter}>
                  <th scope="row">
                    {drop.name}
                    {drop.name === meter && (
                      <span className="slayer-tag">Meter</span>
                    )}
                  </th>
                  <td>{dropRateText(rate, valid)}</td>
                  <td>
                    {valid
                      ? items.toLocaleString("en-US", {
                          maximumSignificantDigits: 3,
                        })
                      : "—"}
                  </td>
                  <td>
                    {price ? (
                      <>
                        <details>
                          <summary>{coins(price.price)}</summary>
                          {number(price.price, 2)} coins
                        </details>
                        <small>{price.source}</small>
                      </>
                    ) : (
                      <span className="slayer-unpriced">Unpriced</span>
                    )}
                  </td>
                  <td>
                    {valid && price ? (
                      <details>
                        <summary>{coins(items * price.price)}</summary>
                        {number(items * price.price, 2)} coins
                      </details>
                    ) : (
                      "—"
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </section>
      {meter && tier.number >= 3 && (
        <p className="slayer-note">
          {meter}: {number(meterRequirement(slayer, meter))} XP guarantee
        </p>
      )}
    </section>
  );
}
function PetPanel({
  pets,
  excludeActive,
}: Readonly<{ pets: ReturnType<typeof petLeveling>; excludeActive: boolean }>) {
  return (
    <section className="slayer-panel" aria-labelledby="pets-title">
      <h2 id="pets-title">Pet leveling</h2>
      <p>
        <strong>{number(pets.profitXp)} XP/hr</strong> ·{" "}
        {excludeActive ? "EXP Share only" : "Main + EXP Share"} · {pets.slots}{" "}
        {pets.slots === 1 ? "slot" : "slots"}
      </p>
      {pets.pets.length ? (
        <ol className="slayer-pets">
          {pets.pets.map((pet) => (
            <li key={`${pet.name}-${pet.rarity}`}>
              <div>
                <strong>{pet.name}</strong>
                <small>
                  {pet.kat
                    ? "Common → Legendary · Kat"
                    : pet.rarity.toLowerCase()}{" "}
                  · {pet.startLevel} → {pet.endLevel}
                </small>
                {pet.kat && (
                  <details>
                    <summary>{coins(pet.kat.total)} Kat upgrades</summary>
                    <p>
                      Fees {number(pet.kat.coins)} · materials{" "}
                      {number(pet.kat.materials)} · {pet.kat.flowers} flowers (
                      {number(pet.kat.flowerCost)} coins)
                    </p>
                  </details>
                )}
              </div>
              <div>
                +{coins(pet.coinsPerHour)}/hr
                <small>{number(pet.coinsPerXp, 2)} coins / XP</small>
              </div>
            </li>
          ))}
        </ol>
      ) : (
        <p className="slayer-note">No reliable pet prices.</p>
      )}
      {!!pets.pets.length && (
        <p className="slayer-note">
          {pets.pets.some((pet) => (pet.historyHours ?? 0) < 168)
            ? "Provisional · building 7-day price history"
            : "7-day prices · spikes excluded"}
        </p>
      )}
    </section>
  );
}
function CalculationDetails({ market }: Readonly<{ market: Market | null }>) {
  return (
    <details className="slayer-assumptions">
      <summary>Calculation details</summary>
      <p>
        Long-run averages with all drops unlocked. A chosen meter item uses the
        best select→unselect cutoff, reselecting at full. Strategy totals
        exclude pets. Taxes and gear costs are excluded.
      </p>
      <p>
        Uses the best Bazaar, AH or NPC price. AH averages three low BINs within
        5%, falling back to recent sales or unstable BINs.
      </p>
      <p>
        Pets: Taming 60, 50% Combat XP Boost, max Beastmaster and EXP Share
        items. Shards add 10% pet XP and 10 points of EXP Share. Applies the
        best pet margin to counted XP. Wisp resale profit is excluded.
      </p>
      <p>
        Pet prices average hourly observations over seven days, excluding
        outliers. Requires three comparable listings per price; after 24
        observations, prices over 50% above or one-third below the baseline are
        excluded. Uses the higher current/average buy price and lower resale
        price. Skins and Tier Boost pets are excluded. Common pets require full
        Legendary XP and all four Kat upgrades, with level-100 coin discounts,
        materials and flowers for each wait deducted.
      </p>
      {market && (
        <dl className="slayer-feed-times">
          {Object.entries(market.feeds).map(([name, feed]) => (
            <div key={name}>
              <dt>{feedNames[name as keyof Market["feeds"]]}</dt>
              <dd>
                {feed.updated
                  ? new Date(feed.updated * 1000).toLocaleString()
                  : "Not loaded"}{" "}
                · {feed.status}
              </dd>
            </div>
          ))}
        </dl>
      )}
    </details>
  );
}
function RngStrategy({
  tierNumber,
  comparison,
  valid,
  meter,
  onSelect,
}: Readonly<{
  tierNumber: number;
  comparison: ReturnType<typeof calculate>["comparison"];
  valid: boolean;
  meter: string;
  onSelect: (item: string) => void;
}>) {
  if (tierNumber < 3) return <p>Requires Tier III or higher.</p>;
  if (!comparison || !valid) return <p>No meter prices.</p>;
  const delta =
    comparison.optimizedCoinsPerHour - comparison.alwaysSelectedCoinsPerHour;
  let heading = `Unselect at ${number((comparison.switchXp / comparison.requirement) * 100, 2)}%`;
  if (comparison.switchXp >= comparison.requirement)
    heading = "Keep selected until full";
  else if (comparison.switchXp === 0) heading = "Leave unselected until full";
  return (
    <>
      <h3>{heading}</h3>
      <p>
        {!meter && "Best item: "}
        {comparison.itemName} · {number(comparison.switchXp, 2)} /{" "}
        {number(comparison.requirement)} XP
      </p>
      {comparison.switchXp < comparison.requirement && (
        <p>Reselect at 100% to claim.</p>
      )}
      <dl className="slayer-comparison">
        <div>
          <dt>Cutoff strategy</dt>
          <dd>
            <strong>{coins(comparison.optimizedCoinsPerHour)}/hr</strong>
          </dd>
        </div>
        <div>
          <dt>Always selected</dt>
          <dd>{coins(comparison.alwaysSelectedCoinsPerHour)}/hr</dd>
        </div>
        <div>
          <dt>Unselected until full</dt>
          <dd>{coins(comparison.fillUnselectedCoinsPerHour)}/hr</dd>
        </div>
      </dl>
      {delta > 0.5 && <p>+{coins(delta)}/hr over always selected</p>}
      {!meter && (
        <button onClick={() => onSelect(comparison.itemName)}>
          Use {comparison.itemName}
        </button>
      )}
    </>
  );
}
function ProfitMetrics({
  result,
  pets,
  valid,
  bph,
  questCost,
  waiting,
  stale,
}: Readonly<{
  result: ReturnType<typeof calculate>;
  pets: ReturnType<typeof petLeveling>;
  valid: boolean;
  bph: number;
  questCost: number;
  waiting: boolean;
  stale: boolean;
}>) {
  const total = result.net + pets.best;
  const signedTotal = `${total >= 0 ? "+" : "−"}${coins(Math.abs(total))}`;
  let detail = "coins";
  if (waiting || stale || result.unpriced > 0 || !pets.pets.length)
    detail = "Partial estimate";
  else if ((pets.pets[0]!.historyHours ?? 0) < 168)
    detail = "Provisional pet prices";
  return (
    <section className="slayer-metrics" aria-label="Estimated profit per hour">
      <Metric
        label="Drop revenue/hr"
        value={valid ? coins(result.gross) : "—"}
      />
      <Metric
        label="Quest fees/hr"
        value={valid ? `−${coins(result.fees)}` : "—"}
        detail={`${number(bph)} bosses/hr · ${coins(questCost)}/boss`}
      />
      <Metric
        label="Pet leveling/hr"
        value={valid && pets.pets.length ? `+${coins(pets.best)}` : "—"}
        detail={pets.pets[0] ? pets.pets[0].name : "No pet prices"}
      />
      <Metric
        label="Total net/hr"
        value={valid ? signedTotal : "—"}
        detail={
          valid
            ? detail
            : waiting
              ? "Waiting for prices"
              : "Estimate unavailable"
        }
        state={valid ? (total >= 0 ? "positive" : "negative") : undefined}
      />
    </section>
  );
}
function MarketStatus({
  waiting,
  stale,
  unpriced,
}: Readonly<{ waiting: boolean; stale: boolean; unpriced: number }>) {
  let state = "ready",
    message = "Market prices loaded";
  if (waiting) {
    state = "pending";
    message = "Loading prices…";
  } else if (stale) {
    state = "stale";
    message = "Prices incomplete or stale";
  }
  return (
    <output className="slayer-market-status">
      <span className="slayer-status-dot" data-state={state} />
      <span>
        {message}
        {unpriced > 0 &&
          ` · ${unpriced} unpriced ${unpriced === 1 ? "drop" : "drops"} excluded`}
      </span>
    </output>
  );
}

function useSlayerMarket() {
  const [market, setMarket] = useState<Market | null>(null);
  const [error, setError] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    let deadline: ReturnType<typeof setTimeout>;
    let active = true;
    async function load() {
      setLoading(true);
      let waiting = false;
      const request = new AbortController();
      const abort = () => request.abort();
      controller.signal.addEventListener("abort", abort, { once: true });
      deadline = setTimeout(abort, 10000);
      try {
        const response = await fetch("/api/v1/slayer-prices", {
          signal: request.signal,
          credentials: "omit",
        });
        if (!response.ok) throw new Error("Market unavailable");
        const value = (await response.json()) as Market;
        if (
          value.version !== 1 ||
          !value.feeds ||
          !value.bazaar ||
          !value.npc ||
          !value.auctions ||
          !Array.isArray(value.pets)
        )
          throw new Error("Invalid market response");
        if (active) {
          setMarket(value);
          setError(false);
        }
        waiting = Object.values(value.feeds).some(
          (feed) => feed.status === "loading",
        );
      } catch {
        if (active) setError(true);
      } finally {
        clearTimeout(deadline);
        controller.signal.removeEventListener("abort", abort);
        if (active) {
          setLoading(false);
          timer = setTimeout(
            () => {
              void load();
            },
            waiting ? 3000 : 60000,
          );
        }
      }
    }
    void load();
    return () => {
      active = false;
      controller.abort();
      clearTimeout(timer);
      clearTimeout(deadline);
    };
  }, [refresh]);

  return {
    market,
    error,
    loading,
    refreshPrices: () => setRefresh((value) => value + 1),
  };
}

function dropRateText(rate: number, valid: boolean) {
  if (!valid) return "—";
  return rate > 1
    ? `${number(rate, 3)} / boss`
    : `${(rate * 100).toLocaleString("en-US", { maximumSignificantDigits: 3 })}%`;
}
const feedNames = {
  npc: "NPC",
  sales: "Recent sales",
  auctions: "Auction House",
  bazaar: "Bazaar",
};
