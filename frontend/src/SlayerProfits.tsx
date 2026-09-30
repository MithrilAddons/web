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
} from "./slayerCalculator";
import "./slayerProfits.css";

const number = (value: number, digits = 0) =>
  value.toLocaleString("en-US", { maximumFractionDigits: digits });
const coins = (value: number) =>
  value.toLocaleString("en-US", {
    notation: "compact",
    maximumFractionDigits: 2,
  });
const roman = ["", "I", "II", "III", "IV", "V"];

export function SlayerProfits() {
  const [slayerIndex, setSlayer] = useState(0);
  const [tierNumber, setTier] = useState(5);
  const [magicFind, setMagicFind] = useState("200");
  const [bosses, setBosses] = useState("60");
  const [meter, setMeter] = useState("");
  const [boost, setBoost] = useState(false);
  const [shards, setShards] = useState(false);
  const [aatroxXp, setAatroxXp] = useState(false);
  const [halfPrice, setHalfPrice] = useState(false);
  const [extraSlots, setExtraSlots] = useState(false);
  const [petXpBoost, setPetXpBoost] = useState(false);
  const [excludeActive, setExcludeActive] = useState(false);
  const [mode, setMode] = useState<"instant" | "offer">("instant");
  const [market, setMarket] = useState<Market | null>(null);
  const [error, setError] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const [loading, setLoading] = useState(true);
  const slayer = slayers[slayerIndex]!;
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
  const total = result.net + pets.best;

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

  const feeds = market ? Object.values(market.feeds) : [];
  const waiting =
    !error && (!market || feeds.some((feed) => feed.status === "loading"));
  const stale =
    error ||
    feeds.some(
      (feed) => feed.status === "stale" || feed.status === "unavailable",
    );
  const comparison = result.comparison;
  const delta = comparison
    ? comparison.optimizedCoinsPerHour - comparison.alwaysSelectedCoinsPerHour
    : 0;

  return (
    <div className="slayer-page">
      <title>Slayer profits · Mithril</title>
      <div className="page-heading slayer-heading">
        <h1>Slayer profits</h1>
        <button
          type="button"
          onClick={() => setRefresh((value) => value + 1)}
          disabled={loading}
        >
          {loading ? "Refreshing…" : "Refresh prices"}
        </button>
      </div>

      <section className="slayer-controls" aria-label="Calculator settings">
        <label>
          Slayer
          <select
            value={slayerIndex}
            onChange={(e) => {
              const index = +e.target.value;
              setSlayer(index);
              setTier(Math.min(tierNumber, slayers[index]!.tiers.length));
              setMeter("");
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
          Tier
          <select
            value={tier.number}
            onChange={(e) => {
              setTier(+e.target.value);
              setMeter("");
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
          Magic Find
          <input
            type="number"
            min="0"
            max="10000"
            step="any"
            value={magicFind}
            onChange={(e) => setMagicFind(e.target.value)}
          />
        </label>
        <label>
          Bosses/hr
          <input
            type="number"
            min="0"
            max="100000"
            step="any"
            value={bosses}
            onChange={(e) => setBosses(e.target.value)}
          />
        </label>
        <label className="slayer-meter">
          RNG meter
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
          Bazaar pricing
          <select
            value={mode}
            onChange={(e) => setMode(e.target.value as "instant" | "offer")}
          >
            <option value="instant">Instant sell</option>
            <option value="offer">Sell offer</option>
          </select>
        </label>
        <div className="slayer-options">
          <fieldset>
            <legend>Aatrox</legend>
            <label>
              <input
                type="checkbox"
                checked={aatroxXp}
                onChange={(e) => setAatroxXp(e.target.checked)}
              />
              +25% RNG meter XP
            </label>
            <label>
              <input
                type="checkbox"
                checked={halfPrice}
                onChange={(e) => setHalfPrice(e.target.checked)}
              />
              Half-price quests
            </label>
          </fieldset>
          <fieldset>
            <legend>Diana</legend>
            <label>
              <input
                type="checkbox"
                checked={extraSlots}
                onChange={(e) => setExtraSlots(e.target.checked)}
              />
              3 EXP Share slots (+10% rate)
            </label>
            <label>
              <input
                type="checkbox"
                checked={petXpBoost}
                onChange={(e) => setPetXpBoost(e.target.checked)}
              />
              +35% pet XP
            </label>
          </fieldset>
          <fieldset>
            <legend>Options</legend>
            <label>
              <input
                type="checkbox"
                checked={boost}
                onChange={(e) => setBoost(e.target.checked)}
              />{" "}
              +10% RNG meter XP
            </label>
            <label>
              <input
                type="checkbox"
                checked={shards}
                onChange={(e) => setShards(e.target.checked)}
              />{" "}
              Pet shard bonuses
            </label>
            <label>
              <input
                type="checkbox"
                checked={excludeActive}
                onChange={(e) => setExcludeActive(e.target.checked)}
              />
              Exclude main pet
            </label>
          </fieldset>
        </div>
      </section>
      {!valid && (
        <p role="alert" className="slayer-warning">
          Enter Magic Find from 0 to 10,000 and bosses/hr from 0 to 100,000.
        </p>
      )}

      <div className="slayer-market-status" role="status">
        <span
          className="slayer-status-dot"
          data-state={waiting ? "pending" : stale ? "stale" : "ready"}
        />
        <span>
          {waiting
            ? "Loading prices…"
            : stale
              ? "Prices incomplete or stale"
              : "Market prices loaded"}
          {result.unpriced > 0 &&
            ` · ${result.unpriced} unpriced ${result.unpriced === 1 ? "drop" : "drops"} excluded`}
        </span>
      </div>

      <section
        className="slayer-metrics"
        aria-label="Estimated profit per hour"
      >
        <Metric
          label="Drop revenue/hr"
          value={valid ? coins(result.gross) : "—"}
        />
        <Metric
          label="Quest fees/hr"
          value={valid ? `−${coins(result.fees)}` : "—"}
          detail={`${number(bph)} bosses/hr · ${coins(tier.questCost * (halfPrice ? 0.5 : 1))}/boss`}
        />
        <Metric
          label="Pet leveling/hr"
          value={valid && pets.pets.length ? `+${coins(pets.best)}` : "—"}
          detail={pets.pets[0] ? pets.pets[0].name : "No pet prices"}
        />
        <Metric
          label="Total net/hr"
          value={
            valid ? `${total >= 0 ? "+" : "−"}${coins(Math.abs(total))}` : "—"
          }
          detail={
            waiting || stale || result.unpriced > 0 || !pets.pets.length
              ? "Partial estimate"
              : (pets.pets[0]!.historyHours ?? 0) < 168
                ? "Provisional pet prices"
                : "coins"
          }
          state={total >= 0 ? "positive" : "negative"}
        />
      </section>

      <section className="slayer-drops" aria-labelledby="drops-title">
        <div className="slayer-section-heading">
          <h2 id="drops-title">Drop breakdown</h2>
          <span>
            {slayer.displayName} {roman[tier.number]}
          </span>
        </div>
        <div
          className="slayer-table-scroll"
          tabIndex={0}
          role="region"
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
                const rate = result.dropRates[i]!;
                const items = rate * amount(drop) * bph;
                return (
                  <tr key={drop.name} data-selected={drop.name === meter}>
                    <th scope="row">
                      {drop.name}
                      {drop.name === meter && (
                        <span className="slayer-tag">Meter</span>
                      )}
                    </th>
                    <td>
                      {valid
                        ? rate > 1
                          ? `${number(rate, 3)} / boss`
                          : `${number(rate * 100, 7)}%`
                        : "—"}
                    </td>
                    <td>{valid ? number(items, 4) : "—"}</td>
                    <td>
                      {price ? (
                        <>
                          <span title={`${number(price.price, 2)} coins`}>
                            {coins(price.price)}
                          </span>
                          <small>{price.source}</small>
                        </>
                      ) : (
                        <span className="slayer-unpriced">Unpriced</span>
                      )}
                    </td>
                    <td>
                      {valid && price ? (
                        <span title={`${number(items * price.price, 2)} coins`}>
                          {coins(items * price.price)}
                        </span>
                      ) : (
                        "—"
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        {meter && tier.number >= 3 && (
          <p className="slayer-note">
            {meter}: {number(meterRequirement(slayer, meter))} XP guarantee
          </p>
        )}
      </section>

      <div className="slayer-bottom-grid">
        <section className="slayer-panel" aria-labelledby="strategy-title">
          <h2 id="strategy-title">RNG strategy</h2>
          {tier.number < 3 ? (
            <p>Requires Tier III or higher.</p>
          ) : comparison && valid ? (
            <>
              <h3>
                {comparison.switchXp >= comparison.requirement
                  ? "Keep selected until full"
                  : comparison.switchXp === 0
                    ? "Leave unselected until full"
                    : `Unselect at ${number((comparison.switchXp / comparison.requirement) * 100, 2)}%`}
              </h3>
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
                    <strong>
                      {coins(comparison.optimizedCoinsPerHour)}/hr
                    </strong>
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
            </>
          ) : (
            <p>No meter prices.</p>
          )}
        </section>
        <section className="slayer-panel" aria-labelledby="pets-title">
          <h2 id="pets-title">Pet leveling</h2>
          <p>
            <strong>{number(pets.profitXp)} XP/hr</strong> ·{" "}
            {excludeActive ? "EXP Share only" : "Main + EXP Share"} ·{" "}
            {pets.slots} {pets.slots === 1 ? "slot" : "slots"}
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
                      <small
                        title={`Kat fees ${number(pet.kat.coins)} + materials ${number(pet.kat.materials)} + flowers ${number(pet.kat.flowerCost)} coins`}
                      >
                        {coins(pet.kat.total)} upgrades incl. {pet.kat.flowers}{" "}
                        flowers
                      </small>
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
      </div>

      <details className="slayer-assumptions">
        <summary>Calculation details</summary>
        <p>
          Long-run averages with all drops unlocked. A chosen meter item uses
          the best select→unselect cutoff, reselecting at full. Strategy totals
          exclude pets. Taxes and gear costs are excluded.
        </p>
        <p>
          Uses the best Bazaar, AH or NPC price. AH averages three low BINs
          within 5%, falling back to recent sales or unstable BINs.
        </p>
        <p>
          Pets: Taming 60, 50% Combat XP Boost, max Beastmaster and EXP Share
          items. Shards add 10% pet XP and 10 points of EXP Share. Applies the
          best pet margin to counted XP. Wisp resale profit is excluded.
        </p>
        <p>
          Pet prices average hourly observations over seven days, excluding
          outliers. Requires three comparable listings per price; after 24
          observations, prices over 50% above or one-third below the baseline
          are excluded. Uses the higher current/average buy price and lower
          resale price. Skins and Tier Boost pets are excluded. Common pets
          require full Legendary XP and all four Kat upgrades, with level-100
          coin discounts, materials and flowers for each wait deducted.
        </p>
        {market && (
          <dl className="slayer-feed-times">
            {Object.entries(market.feeds).map(([name, feed]) => (
              <div key={name}>
                <dt>
                  {name === "npc"
                    ? "NPC"
                    : name === "sales"
                      ? "Recent sales"
                      : name === "auctions"
                        ? "Auction House"
                        : "Bazaar"}
                </dt>
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
    </div>
  );
}

function Metric({
  label,
  value,
  detail,
  state,
}: {
  label: string;
  value: string;
  detail?: string;
  state?: string;
}) {
  return (
    <div className="slayer-metric" data-state={state}>
      <h2>{label}</h2>
      <strong>{value}</strong>
      {detail && <p>{detail}</p>}
    </div>
  );
}
