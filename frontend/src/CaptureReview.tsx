import { useEffect, useState } from "react";
import { request } from "./moderationApi";

type Kind = "locations" | "maps";
type Status =
  | "submitted"
  | "approved"
  | "changes_requested"
  | "rejected"
  | "retired"
  | "all";
type Corners = { min_x: number; min_z: number; max_x: number; max_z: number };
type Submission = Corners & {
  id: string;
  name: string | null;
  island: string;
  island_name: string;
  status: Exclude<Status, "all"> | "uploading";
  reviewer_note: string | null;
  updated: number;
  x: number;
  y: number;
  z: number;
  note: string;
  captured_at: number;
};
type Queue = {
  total: number;
  items: Submission[];
  current_maps: Record<string, Corners & { id: string }>;
};

const STATUS: Record<Status, string> = {
  submitted: "Waiting for review",
  approved: "Approved",
  changes_requested: "Changes requested",
  rejected: "Rejected",
  retired: "Retired",
  all: "All",
};
// Minecraft's panorama order, laid out as an unfolded cube.
const CROSS: { face: number; label: string; column: number; row: number }[] = [
  { face: 4, label: "Up", column: 2, row: 1 },
  { face: 3, label: "Left", column: 1, row: 2 },
  { face: 0, label: "Front", column: 2, row: 2 },
  { face: 1, label: "Right", column: 3, row: 2 },
  { face: 2, label: "Back", column: 4, row: 2 },
  { face: 5, label: "Down", column: 2, row: 3 },
];
const BASE = "/api/v1/moderation/captures";
const DONE: Record<string, string> = {
  approve: "Approved.",
  changes: "Sent back.",
  reject: "Rejected.",
  retire: "Retired: it's out of the game.",
};

export function CaptureReview() {
  const [kind, setKind] = useState<Kind>("locations");
  const [status, setStatus] = useState<Status>("submitted");
  const [queue, setQueue] = useState<Queue | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);

  async function load(offset = 0) {
    const page = await request<Queue>(
      `captures?kind=${kind}&status=${status}&offset=${offset}`,
    );
    setQueue((previous) =>
      offset && previous
        ? { ...page, items: [...previous.items, ...page.items] }
        : page,
    );
  }

  useEffect(() => {
    let active = true;
    setError("");
    request<Queue>(`captures?kind=${kind}&status=${status}&offset=0`).then(
      (page) => {
        if (active) setQueue(page);
      },
      (err: Error) => {
        if (active) setError(err.message);
      },
    );
    return () => {
      active = false;
    };
  }, [kind, status]);

  async function decide(item: Submission, decision: string, note: string) {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await request("captures/decide", { kind, id: item.id, decision, note });
      setNotice(DONE[decision] ?? "Saved.");
      await load();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="content-stack capture-review">
      <h2>Captures</h2>
      <div className="moderation-search">
        <fieldset className="segmented capture-kind">
          <legend className="sr-only">Submission type</legend>
          {(["locations", "maps"] as const).map((value) => (
            <button
              key={value}
              type="button"
              aria-pressed={kind === value}
              onClick={() => setKind(value)}
            >
              {value === "locations" ? "Locations" : "Maps"}
            </button>
          ))}
        </fieldset>
        <label>
          Show{" "}
          <select
            value={status}
            onChange={(event) => setStatus(event.target.value as Status)}
          >
            {(Object.keys(STATUS) as Status[]).map((value) => (
              <option key={value} value={value}>
                {STATUS[value]}
              </option>
            ))}
          </select>
        </label>
        {queue && <span className="quiet-label">{queue.total} in total</span>}
      </div>
      {error && <p role="alert">{error}</p>}
      {notice && <output>{notice}</output>}
      {queue && !queue.items.length && <p>Nothing here.</p>}
      <ul className="capture-list">
        {queue?.items.map((item) => (
          <li key={item.id}>
            {kind === "locations" ? (
              <LocationCard item={item} map={queue.current_maps[item.island]} />
            ) : (
              <MapCard item={item} current={queue.current_maps[item.island]} />
            )}
            {item.status === "submitted" ||
            item.status === "changes_requested" ? (
              <DecisionForm
                busy={busy}
                onDecide={(decision, note) => void decide(item, decision, note)}
              />
            ) : (
              <div className="moderation-actions">
                <p className="quiet-label">
                  {item.status === "approved" && kind === "locations"
                    ? "Live in the game"
                    : (STATUS[item.status as Status] ?? item.status)}
                  {item.reviewer_note ? ` · ${item.reviewer_note}` : ""}
                </p>
                {item.status === "approved" && kind === "locations" && (
                  <button
                    type="button"
                    className="secondary"
                    disabled={busy}
                    onClick={() => void decide(item, "retire", "")}
                  >
                    Retire
                  </button>
                )}
              </div>
            )}
          </li>
        ))}
      </ul>
      {queue && queue.items.length < queue.total && (
        <button
          type="button"
          className="secondary"
          disabled={busy}
          onClick={() => void load(queue.items.length)}
        >
          Load more
        </button>
      )}
    </section>
  );
}

function LocationCard({
  item,
  map,
}: Readonly<{ item: Submission; map?: Corners & { id: string } }>) {
  return (
    <div className="capture-card">
      <div className="capture-cross" aria-label="Panorama faces">
        {CROSS.map(({ face, label, column, row }) => (
          <img
            key={face}
            src={`${BASE}/locations/${item.id}/faces/${face}.png`}
            alt={`${label} face`}
            loading="lazy"
            style={{ gridColumn: column, gridRow: row }}
          />
        ))}
      </div>
      <div className="capture-details">
        <h3>{item.island_name}</h3>
        <p className="quiet-label">
          {item.island} · x {Math.round(item.x)} · y {Math.round(item.y)} · z{" "}
          {Math.round(item.z)}
        </p>
        {item.note && <p>“{item.note}”</p>}
        <p className="quiet-label">
          {item.name ?? "Erased account"} ·{" "}
          {new Date(item.captured_at).toLocaleString()}
        </p>
        {map ? (
          <Spot map={map} x={item.x} z={item.z} />
        ) : (
          <p className="quiet-label">No approved map of this island yet.</p>
        )}
      </div>
    </div>
  );
}

function Spot({
  map,
  x,
  z,
}: Readonly<{ map: Corners & { id: string }; x: number; z: number }>) {
  const width = map.max_x - map.min_x + 1;
  const height = map.max_z - map.min_z + 1;
  const left = ((x - map.min_x) / width) * 100;
  const top = ((z - map.min_z) / height) * 100;
  const inside = left >= 0 && left <= 100 && top >= 0 && top <= 100;
  return (
    <figure className="capture-spot">
      <img src={`${BASE}/maps/${map.id}.png`} alt="Current island map" />
      {inside && (
        <span
          className="capture-pin"
          style={{ left: `${left}%`, top: `${top}%` }}
        />
      )}
      {!inside && (
        <figcaption role="alert">
          This spot is outside the island’s current map.
        </figcaption>
      )}
    </figure>
  );
}

function MapCard({
  item,
  current,
}: Readonly<{ item: Submission; current?: Corners & { id: string } }>) {
  return (
    <div className="capture-card capture-maps">
      <figure>
        <img src={`${BASE}/maps/${item.id}.png`} alt="Submitted map" />
        <figcaption className="quiet-label">
          {item.island_name} · {item.max_x - item.min_x + 1}×
          {item.max_z - item.min_z + 1} blocks from ({item.min_x}, {item.min_z})
          · {item.name ?? "Erased account"}
        </figcaption>
      </figure>
      {current && current.id !== item.id && (
        <figure>
          <img src={`${BASE}/maps/${current.id}.png`} alt="Current map" />
          <figcaption className="quiet-label">Current map</figcaption>
        </figure>
      )}
    </div>
  );
}

function DecisionForm({
  busy,
  onDecide,
}: Readonly<{
  busy: boolean;
  onDecide: (decision: string, note: string) => void;
}>) {
  const [note, setNote] = useState("");
  return (
    <div className="moderation-actions">
      <label>
        Note for the capturer{" "}
        <input
          value={note}
          maxLength={500}
          placeholder="Needed to send back or reject"
          onChange={(event) => setNote(event.target.value)}
        />
      </label>
      <button
        type="button"
        className="primary"
        disabled={busy}
        onClick={() => onDecide("approve", note)}
      >
        Approve
      </button>
      <button
        type="button"
        className="secondary"
        disabled={busy || !note.trim()}
        onClick={() => onDecide("changes", note)}
      >
        Request changes
      </button>
      <button
        type="button"
        className="secondary"
        disabled={busy || !note.trim()}
        onClick={() => onDecide("reject", note)}
      >
        Reject
      </button>
    </div>
  );
}
