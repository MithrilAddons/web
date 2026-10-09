import { useEffect, useState } from "react";
import { request } from "./moderationApi";

type QueueDay = {
  day: string;
  item: string | null;
  name: string | null;
  sales: number | null;
  locked: boolean;
};
type Overview = {
  sales_cutoff: number;
  sales_since: string | null;
  counts: Record<string, number>;
  new: number;
  queue: QueueDay[];
};
type Item = {
  id: string;
  name: string;
  rarity: string | null;
  museum: string | null;
  sales: number;
  list: "allow" | "block" | null;
  status: string;
  admin: boolean;
  new: boolean;
};
type Group = "pool" | "admin" | "new" | "allowed" | "blocked" | "all";

const GROUPS: Record<Group, string> = {
  pool: "Answer pool",
  admin: "Admin giveaways",
  new: "New since last review",
  allowed: "Allowlist",
  blocked: "Blocklist",
  all: "All items",
};
const STATUS: Record<string, string> = {
  eligible: "In pool",
  allowed: "Allowed",
  blocked: "Blocked",
  popular: "Too popular",
  cosmetic: "Cosmetic",
  not_unique: "Looks like another item",
};

function words(value: string | null) {
  return value ? value.replaceAll("_", " ").toLowerCase() : "—";
}

export function CuratorReview() {
  const [overview, setOverview] = useState<Overview | null>(null);
  const [cutoff, setCutoff] = useState("");
  const [group, setGroup] = useState<Group>("pool");
  const [query, setQuery] = useState("");
  const [items, setItems] = useState<Item[]>([]);
  const [total, setTotal] = useState(0);
  const [day, setDay] = useState("");
  const [item, setItem] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);

  async function load(next = group, search = query) {
    const [summary, page] = await Promise.all([
      request<Overview>("curator"),
      request<{ total: number; items: Item[] }>(
        `curator/items?group=${next}&query=${encodeURIComponent(search)}`,
      ),
    ]);
    setOverview(summary);
    setCutoff(String(summary.sales_cutoff));
    setItems(page.items);
    setTotal(page.total);
  }

  async function act(
    action: () => Promise<unknown>,
    done = "Saved.",
    reload = true,
  ) {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await action();
      if (reload) await load();
      setNotice(done);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Request failed");
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    let active = true;
    void load().catch((err: Error) => {
      if (active) setError(err.message);
    });
    return () => {
      active = false;
    };
  }, []);

  const coming = overview?.queue.filter((entry) => !entry.locked) ?? [];
  const pool =
    (overview?.counts.eligible ?? 0) + (overview?.counts.allowed ?? 0);

  return (
    <section className="content-stack curator-review">
      <h2>Curator</h2>
      {error && <p role="alert">{error}</p>}
      {notice && <output>{notice}</output>}
      {!overview && !error && <output>Loading Curator…</output>}
      {overview && (
        <>
          <p>
            {pool} items in the answer pool. Auction sales collected since{" "}
            {overview.sales_since ?? "no sales yet"}. {overview.new} new items
            since the last review.
          </p>
          <form
            className="moderation-search"
            onSubmit={(event) => {
              event.preventDefault();
              void act(() =>
                request("curator/settings", { sales_cutoff: Number(cutoff) }),
              );
            }}
          >
            <label>
              Too popular above (auction sales in 30 days){" "}
              <input
                type="number"
                min={0}
                max={1000000}
                required
                value={cutoff}
                onChange={(e) => setCutoff(e.target.value)}
              />
            </label>
            <button type="submit" disabled={busy}>
              Save cut-off
            </button>
            <button
              type="button"
              className="secondary"
              disabled={busy}
              onClick={() =>
                void act(
                  () => request("curator/reviewed", {}),
                  "Marked reviewed.",
                )
              }
            >
              Mark all reviewed
            </button>
          </form>
          <h3>Answer queue</h3>
          <div className="detail-table-wrap">
            <table className="detail-table">
              <thead>
                <tr>
                  <th scope="col">Day (UTC)</th>
                  <th scope="col">Item</th>
                  <th scope="col">Sales</th>
                  <th scope="col">
                    <span className="sr-only">Actions</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {overview.queue.map((entry) => (
                  <tr key={entry.day}>
                    <td>{entry.day}</td>
                    <td>{entry.name ?? "No item available"}</td>
                    <td>{entry.sales ?? "—"}</td>
                    <td>
                      {entry.locked ? (
                        <span className="quiet-label">Today</span>
                      ) : (
                        <button
                          type="button"
                          className="secondary"
                          disabled={busy}
                          onClick={() =>
                            void act(() =>
                              request("curator/day", {
                                day: entry.day,
                                item: null,
                              }),
                            )
                          }
                        >
                          Reroll
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <form
            className="moderation-search"
            onSubmit={(event) => {
              event.preventDefault();
              void act(() =>
                request("curator/day", { day, item: item.trim() }),
              );
            }}
          >
            <label>
              Day{" "}
              <select
                required
                value={day}
                onChange={(e) => setDay(e.target.value)}
              >
                <option value="">Choose a day</option>
                {coming.map((entry) => (
                  <option key={entry.day} value={entry.day}>
                    {entry.day}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Item ID{" "}
              <input
                required
                maxLength={128}
                value={item}
                onChange={(e) => setItem(e.target.value)}
                placeholder="SYNTHESIZER_V3"
              />
            </label>
            <button type="submit" disabled={busy}>
              Schedule item
            </button>
          </form>
          <h3>Items</h3>
          <form
            className="moderation-search"
            onSubmit={(event) => {
              event.preventDefault();
              void act(() => load(group, query), "", false);
            }}
          >
            <label>
              Group{" "}
              <select
                value={group}
                onChange={(e) => {
                  const next = e.target.value as Group;
                  setGroup(next);
                  void act(() => load(next, query), "", false);
                }}
              >
                {(Object.keys(GROUPS) as Group[]).map((key) => (
                  <option key={key} value={key}>
                    {GROUPS[key]}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Search{" "}
              <input
                value={query}
                maxLength={64}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Item name or ID"
              />
            </label>
            <button type="submit" disabled={busy}>
              Search
            </button>
          </form>
          <p className="quiet-label">
            Showing {items.length} of {total}
          </p>
          <div className="detail-table-wrap">
            <table className="detail-table">
              <thead>
                <tr>
                  <th scope="col">Item</th>
                  <th scope="col">Rarity</th>
                  <th scope="col">Museum</th>
                  <th scope="col">Sales</th>
                  <th scope="col">Status</th>
                  <th scope="col">
                    <span className="sr-only">Actions</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {items.map((row) => (
                  <tr key={row.id}>
                    <td>
                      {row.name} <code>{row.id}</code>
                    </td>
                    <td>{words(row.rarity)}</td>
                    <td>{words(row.museum)}</td>
                    <td>{row.sales}</td>
                    <td>{STATUS[row.status] ?? row.status}</td>
                    <td className="curator-actions">
                      {(["allow", "block"] as const).map((list) => (
                        <button
                          key={list}
                          type="button"
                          className="secondary"
                          aria-pressed={row.list === list}
                          aria-label={`${list === "allow" ? "Allow" : "Block"} ${row.name}`}
                          disabled={busy}
                          onClick={() =>
                            void act(() =>
                              request("curator/list", {
                                item: row.id,
                                list: row.list === list ? null : list,
                              }),
                            )
                          }
                        >
                          {list === "allow" ? "Allow" : "Block"}
                        </button>
                      ))}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {items.length < total && (
            <button
              type="button"
              className="secondary"
              disabled={busy}
              onClick={() =>
                void act(
                  async () => {
                    const page = await request<{
                      total: number;
                      items: Item[];
                    }>(
                      `curator/items?group=${group}&query=${encodeURIComponent(query)}&offset=${items.length}`,
                    );
                    setItems([...items, ...page.items]);
                  },
                  "",
                  false,
                )
              }
            >
              Show more
            </button>
          )}
        </>
      )}
    </section>
  );
}
