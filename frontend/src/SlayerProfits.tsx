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
    () => calculate(slayer, tier, mf, bph, meter || null, prices, boost),
    [slayer, tier, mf, bph, meter, prices, boost],
  );
  const pets = useMemo(
    () => petLeveling(tier, bph, market?.pets ?? [], shards),
    [tier, bph, market, shards],
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
    ? comparison.fillUnselectedCoinsPerHour -
      comparison.alwaysSelectedCoinsPerHour
    : 0;

  return (
    <div className="slayer-page">
      <title>Slayer profits · Mithril</title>
      <div className="page-heading slayer-heading">
        <div>
          <p className="slayer-eyebrow">SkyBlock calculator</p>
          <h1>Slayer profits</h1>
          <p className="slayer-subtitle">
            Plan your next grind with expected drops, market prices, and pet XP.
          </p>
        </div>
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
          Bosses per hour
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
          <span>{number(tier.questCost)} coins / quest</span>
        </div>
      </section>
      {!valid && (
        <p role="alert" className="slayer-warning">
          Enter Magic Find from 0 to 10,000 and bosses per hour from 0 to
          100,000.
        </p>
      )}

      <div className="slayer-market-status" role="status">
        <span
          className="slayer-status-dot"
          data-state={waiting ? "pending" : stale ? "stale" : "ready"}
        />
        <span>
          {waiting
            ? "Loading market prices. Auction House scanning may take a minute."
            : stale
              ? "Some market prices are unavailable or stale. Available prices are shown below."
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
          label="Drop revenue / h"
          value={valid ? coins(result.gross) : "—"}
          detail="At the best available sale price"
        />
        <Metric
          label="Quest fees / h"
          value={valid ? `−${coins(result.fees)}` : "—"}
          detail={`${number(bph)} quests per hour`}
        />
        <Metric
          label="Pet leveling / h"
          value={valid && pets.pets.length ? `+${coins(pets.best)}` : "—"}
          detail={
            pets.pets[0]
              ? pets.pets[0].name
              : "Waiting for a profitable pet pair"
          }
        />
        <Metric
          label="Total net / h"
          value={
            valid ? `${total >= 0 ? "+" : "−"}${coins(Math.abs(total))}` : "—"
          }
          detail={
            waiting || stale || result.unpriced > 0
              ? "Partial estimate · coins"
              : "Expected profit · coins"
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
                <th scope="col">Items / h</th>
                <th scope="col">Unit price</th>
                <th scope="col">Coins / h</th>
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
        <p className="slayer-note">
          Rates are long-run averages.{" "}
          {meter && tier.number >= 3
            ? `${meter}: ${number(meterRequirement(slayer, meter))} XP guarantee, modeled from an empty meter.`
            : "Select an RNG meter item to include its bonus and guarantee."}
        </p>
      </section>

      <div className="slayer-bottom-grid">
        <section className="slayer-panel" aria-labelledby="strategy-title">
          <p className="slayer-eyebrow">RNG meter</p>
          <h2 id="strategy-title">Compare strategies</h2>
          {tier.number < 3 ? (
            <p>Meter XP only accumulates from Tier III bosses and above.</p>
          ) : comparison && valid ? (
            <>
              <h3>
                {Math.abs(delta) <= 0.5
                  ? "Both approaches are effectively equal"
                  : delta > 0
                    ? "Fill unselected, then claim the guarantee"
                    : "Keep the item selected"}
              </h3>
              <p>
                {comparison.itemName}
                {Math.abs(delta) > 0.5 && (
                  <>
                    {" "}
                    · <strong>+{coins(Math.abs(delta))} coins / h</strong>{" "}
                    compared with the other approach
                  </>
                )}
              </p>
              <dl className="slayer-comparison">
                <div>
                  <dt>Always selected</dt>
                  <dd>{coins(comparison.alwaysSelectedCoinsPerHour)} / h</dd>
                </div>
                <div>
                  <dt>Fill unselected</dt>
                  <dd>{coins(comparison.fillUnselectedCoinsPerHour)} / h</dd>
                </div>
              </dl>
              <p className="slayer-note">
                Compares the highest-value priced meter drop. These totals
                exclude pet leveling.
              </p>
            </>
          ) : (
            <p>Waiting for a price for an eligible meter item.</p>
          )}
        </section>
        <section className="slayer-panel" aria-labelledby="pets-title">
          <p className="slayer-eyebrow">Combat pets</p>
          <h2 id="pets-title">Pet leveling</h2>
          <p>
            <strong>{number(pets.active + pets.shared)} XP / h</strong> ·{" "}
            {number(pets.active)} active + {number(pets.shared)} EXP Share
          </p>
          {pets.pets.length ? (
            <ol className="slayer-pets">
              {pets.pets.map((pet) => (
                <li key={`${pet.name}-${pet.rarity}`}>
                  <div>
                    <strong>{pet.name}</strong>
                    <small>
                      {pet.rarity.toLowerCase()} · {pet.startLevel} →{" "}
                      {pet.endLevel}
                    </small>
                  </div>
                  <div>
                    +{coins(pet.coinsPerHour)} / h
                    <small>{number(pet.coinsPerXp, 2)} coins / XP</small>
                  </div>
                </li>
              ))}
            </ol>
          ) : (
            <p className="slayer-note">
              No profitable pet pairs are available yet. Pet profit is excluded
              until prices load.
            </p>
          )}
        </section>
      </div>

      <details className="slayer-assumptions">
        <summary>Prices & calculation assumptions</summary>
        <p>
          Uses the original MithrilAddons calculator’s five non-Vampire Slayer
          tables. Assumes all listed drops are unlocked. Expected drops use
          separate Main and Extra pools, Magic Find, and RNG-meter cycles;
          individual sessions can vary substantially.
        </p>
        <p>
          Prices choose the highest of Bazaar, Auction House, and NPC value.
          Bazaar uses instant-sell or sell-offer estimates. Stable Auction House
          quotes average the three lowest BINs within 5%; otherwise recent sales
          are preferred, with sparse or widely spread listings marked “Unstable
          BIN”. Taxes, gear costs, and other expenses are not deducted.
        </p>
        <p>
          Pet estimates assume Taming 60, a 50% Combat XP Boost, max
          Beastmaster, and one EXP Share pet with the EXP Share item. Shard
          bonuses add 10% Combat pet XP and 10 percentage points to EXP Share.
          The best pet margin is applied to active and shared XP; auction
          margins are estimates, not completed sales. Wisp pets are excluded.
        </p>
        <p>
          Bazaar refreshes every 5 minutes, auctions every 15 minutes, and NPC
          values hourly. Recent sales cover at most 24 hours collected while the
          calculator is in use and reset on service restart. Refresh checks the
          shared cache; it does not force another full scan.
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
  detail: string;
  state?: string;
}) {
  return (
    <div className="slayer-metric" data-state={state}>
      <h2>{label}</h2>
      <strong>{value}</strong>
      <p>{detail}</p>
    </div>
  );
}
