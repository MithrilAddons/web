import {
  useCallback,
  useEffect,
  useId,
  useMemo,
  useState,
  type KeyboardEvent,
} from "react";
import {
  CuratorError,
  getCatalog,
  getLeaderboard,
  getToday,
  iconUrl,
  sendGuess,
  type Leaderboard,
  type Today,
} from "./curatorApi";
import {
  COLUMNS,
  RARITY_COLOUR,
  arrowText,
  cell,
  countdown,
  exact,
  full,
  hint,
  known,
  share,
  suggestions,
  type CatalogItem,
  type ColumnInfo,
  type Guess,
} from "./curatorFormat";
import { ModDownload } from "./ModDownload";
import "./curator.css";

type View = "today" | "leaderboard";
type Playing = Exclude<Today, { state: "preparing" }>;
const VIEW_KEY = "mithril.curator.view";
const NARROW = "(max-width: 760px)";

function storedView(): View {
  try {
    return localStorage.getItem(VIEW_KEY) === "leaderboard"
      ? "leaderboard"
      : "today";
  } catch {
    return "today";
  }
}

function useNarrow() {
  const [narrow, setNarrow] = useState(
    () =>
      typeof window.matchMedia === "function" &&
      window.matchMedia(NARROW).matches,
  );
  useEffect(() => {
    if (typeof window.matchMedia !== "function") return;
    const list = window.matchMedia(NARROW);
    const update = () => setNarrow(list.matches);
    list.addEventListener("change", update);
    return () => list.removeEventListener("change", update);
  }, []);
  return narrow;
}

function useNow() {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 30_000);
    return () => clearInterval(timer);
  }, []);
  return now;
}

/** Runs `refresh` whenever the tab comes back into view. */
function useReturnRefresh(refresh: () => void) {
  useEffect(() => {
    const run = () => {
      if (document.visibilityState === "visible") refresh();
    };
    document.addEventListener("visibilitychange", run);
    window.addEventListener("focus", run);
    return () => {
      document.removeEventListener("visibilitychange", run);
      window.removeEventListener("focus", run);
    };
  }, [refresh]);
}

export function Curator() {
  const [view, setView] = useState<View>(storedView);
  const choose = (next: View) => {
    setView(next);
    try {
      localStorage.setItem(VIEW_KEY, next);
    } catch {
      // The choice just isn't remembered.
    }
  };
  return (
    <>
      <title>Curator · Mithril</title>
      <div className="page-heading curator-heading">
        <div>
          <h1>Curator</h1>
          <p className="quiet-label">
            Guess today’s SkyBlock item in 10 tries. One round a day, shared
            with the MithrilPF mod.
          </p>
        </div>
        <div className="segmented" role="group" aria-label="Curator view">
          <button
            type="button"
            aria-pressed={view === "today"}
            onClick={() => choose("today")}
          >
            Today
          </button>
          <button
            type="button"
            aria-pressed={view === "leaderboard"}
            onClick={() => choose("leaderboard")}
          >
            Leaderboard
          </button>
        </div>
      </div>
      {view === "today" ? <TodayView /> : <LeaderboardView />}
      <p className="curator-credit">
        Item art © Hypixel Inc., from the Hypixel SkyBlock Resource Pack.
      </p>
    </>
  );
}

function SignedOut({ what }: Readonly<{ what: string }>) {
  return (
    <section className="curator-panel curator-signed-out">
      <p>Link your Minecraft account to {what}.</p>
      <p className="quiet-label">
        Open <code>/mpf</code> in Minecraft, select{" "}
        <strong>Link browser</strong>, then confirm here.
      </p>
      <a className="button primary" href="/link">
        Enter a linking code
      </a>
      <ModDownload />
    </section>
  );
}

function TodayView() {
  const [today, setToday] = useState<Today | null>(null);
  const [items, setItems] = useState<CatalogItem[]>([]);
  const [blocked, setBlocked] = useState<"signed_out" | "banned" | null>(null);
  const [error, setError] = useState("");
  const [stale, setStale] = useState(false);
  const now = useNow();
  const narrow = useNarrow();

  const fail = useCallback((problem: unknown) => {
    const status = problem instanceof CuratorError ? problem.status : 0;
    if (status === 401) setBlocked("signed_out");
    else if (status === 403) setBlocked("banned");
    else if (
      problem instanceof CuratorError &&
      problem.message === "A new item is ready"
    )
      setStale(true);
    else
      setError(
        problem instanceof CuratorError
          ? problem.message
          : "Something went wrong. Try again.",
      );
  }, []);

  const load = useCallback(() => {
    getToday()
      .then((value) => {
        setToday(value);
        setStale(false);
        setBlocked(null);
        setError("");
      })
      .catch(fail);
  }, [fail]);

  useEffect(() => {
    load();
    getCatalog()
      .then(setItems)
      .catch(() => undefined);
  }, [load]);
  useReturnRefresh(load);

  const guess = useCallback(
    async (item: string) => {
      if (!today) return false;
      try {
        setToday(await sendGuess(today.day, item));
        setError("");
        return true;
      } catch (problem) {
        fail(problem);
        return false;
      }
    },
    [today, fail],
  );

  if (blocked === "signed_out") return <SignedOut what="play Curator" />;
  if (blocked === "banned")
    return <p role="alert">This account can’t play Curator.</p>;
  if (!today)
    return error ? (
      <p role="alert">{error}</p>
    ) : (
      <p className="quiet-label">Loading today’s item…</p>
    );
  const newDay = stale || now >= today.resets_at * 1000;
  const next = countdown(today.resets_at * 1000 - now);
  if (today.state === "preparing")
    return (
      <section className="curator-panel">
        <p>Today’s item is being prepared…</p>
        <p className="quiet-label">New item in {next}</p>
      </section>
    );
  return (
    <Round
      today={today}
      items={items}
      narrow={narrow}
      newDay={newDay}
      next={next}
      error={error}
      onError={setError}
      onGuess={guess}
      onLoad={load}
    />
  );
}

function Round({
  today,
  items,
  narrow,
  newDay,
  next,
  error,
  onError,
  onGuess,
  onLoad,
}: Readonly<{
  today: Playing;
  items: CatalogItem[];
  narrow: boolean;
  newDay: boolean;
  next: string;
  error: string;
  onError: (message: string) => void;
  onGuess: (item: string) => Promise<boolean>;
  onLoad: () => void;
}>) {
  const guessed = useMemo(
    () => new Set(today.guesses.map((entry) => entry.item)),
    [today.guesses],
  );
  const finished = today.state !== "playing";
  const left = today.limit - today.guesses.length;
  const box =
    finished || newDay ? null : (
      <GuessBox
        items={items}
        guessed={guessed}
        upward={narrow}
        onGuess={onGuess}
        onError={onError}
      />
    );
  return (
    <section className="curator-round" aria-labelledby="curator-number">
      <div className="curator-round-head">
        <h2 id="curator-number">Curator #{today.number}</h2>
        <span className="quiet-label">
          {today.guesses.length} of {today.limit} guesses
        </span>
      </div>
      {newDay && (
        <div className="curator-new-day">
          <p>A new item is ready</p>
          <button type="button" className="primary" onClick={onLoad}>
            Load new item
          </button>
        </div>
      )}
      {finished && <Result today={today} next={next} />}
      {!narrow && box}
      {error && <p role="alert">{error}</p>}
      {!finished && !newDay && (
        <p className="quiet-label curator-status">
          {left} guesses left · New item in {next}
        </p>
      )}
      {narrow ? (
        <>
          {today.guesses.length > 0 && <KnownPanel guesses={today.guesses} />}
          <GuessList key={today.day} guesses={today.guesses} />
          {box && <div className="curator-dock">{box}</div>}
        </>
      ) : (
        <ClueGrid
          guesses={today.guesses}
          limit={finished ? today.guesses.length : today.limit}
        />
      )}
    </section>
  );
}

function GuessBox({
  items,
  guessed,
  upward,
  onGuess,
  onError,
}: Readonly<{
  items: CatalogItem[];
  guessed: ReadonlySet<string>;
  upward: boolean;
  onGuess: (item: string) => Promise<boolean>;
  onError: (message: string) => void;
}>) {
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const [busy, setBusy] = useState(false);
  const list = useId();
  const matches = useMemo(
    () => suggestions(items, query, guessed),
    [items, query, guessed],
  );
  const showing = open && matches.length > 0;
  const shown = upward ? [...matches].reverse() : matches;

  const pick = (item: CatalogItem) => {
    setQuery(item[1]);
    setOpen(false);
  };
  const submit = async (item: CatalogItem | undefined) => {
    if (!item) {
      onError("Pick an item from the list");
      return;
    }
    setBusy(true);
    setOpen(false);
    if (await onGuess(item[0])) setQuery("");
    setBusy(false);
  };
  const key = (event: KeyboardEvent<HTMLInputElement>) => {
    const move = (step: number) => {
      event.preventDefault();
      setOpen(true);
      setActive(
        (current) =>
          (current + step + matches.length) % Math.max(matches.length, 1),
      );
    };
    const down = upward ? -1 : 1;
    switch (event.key) {
      case "ArrowDown":
        move(down);
        break;
      case "ArrowUp":
        move(-down);
        break;
      case "Tab":
        if (showing && matches[active]) {
          event.preventDefault();
          pick(matches[active]);
        }
        break;
      case "Escape":
        setOpen(false);
        break;
      case "Enter":
        event.preventDefault();
        if (showing && matches[active] && !exact(items, query))
          pick(matches[active]);
        else
          void submit(
            exact(items, query) ?? (showing ? matches[active] : undefined),
          );
        break;
    }
  };

  return (
    <div className={`curator-guess${upward ? " is-upward" : ""}`}>
      <div className="curator-combo">
        <input
          role="combobox"
          aria-label="Item name"
          aria-expanded={showing}
          aria-controls={list}
          aria-autocomplete="list"
          aria-activedescendant={showing ? `${list}-${active}` : undefined}
          placeholder="Type an item name"
          autoComplete="off"
          spellCheck={false}
          maxLength={64}
          value={query}
          disabled={busy}
          onChange={(event) => {
            setQuery(event.target.value);
            setActive(0);
            setOpen(true);
            onError("");
          }}
          onBlur={() => setOpen(false)}
          onKeyDown={key}
        />
        {showing && (
          <ul className="curator-suggestions" role="listbox" id={list}>
            {shown.map((item) => {
              const index = matches.indexOf(item);
              return (
                <li
                  key={item[0]}
                  id={`${list}-${index}`}
                  role="option"
                  aria-selected={index === active}
                  onMouseDown={(event) => {
                    event.preventDefault();
                    pick(item);
                  }}
                  onMouseEnter={() => setActive(index)}
                >
                  {item[1]}
                </li>
              );
            })}
          </ul>
        )}
      </div>
      <button
        type="button"
        className="primary"
        disabled={busy}
        onClick={() => void submit(exact(items, query) ?? matches[0])}
      >
        Guess
      </button>
    </div>
  );
}

/** A missing icon keeps its space in lists, so names stay aligned, unless `collapse`. */
function Icon({
  item,
  collapse = false,
}: Readonly<{ item: string; collapse?: boolean }>) {
  return (
    <img
      className="curator-icon"
      src={iconUrl(item)}
      alt=""
      width={20}
      height={20}
      loading="lazy"
      onError={(event) => {
        if (collapse) event.currentTarget.hidden = true;
        else event.currentTarget.style.visibility = "hidden";
      }}
    />
  );
}

function ItemName({ guess }: Readonly<{ guess: Guess }>) {
  return (
    <span className="curator-item">
      <Icon item={guess.item} />
      <span className="curator-item-name">{guess.name}</span>
      {guess.family && (
        <span
          className="curator-family"
          title="Another tier of the answer's upgrade chain"
        >
          family
        </span>
      )}
    </span>
  );
}

function describe(column: ColumnInfo, guess: Guess) {
  const feedback = guess.feedback[column.key];
  return `${column.name}: ${full(column.key, guess.values)}. ${hint(column.key, feedback)}`;
}

function ClueGrid({
  guesses,
  limit,
}: Readonly<{ guesses: readonly Guess[]; limit: number }>) {
  return (
    <div className="curator-grid-wrap">
      <table className="curator-grid">
        <thead>
          <tr>
            <th scope="col">Item</th>
            {COLUMNS.map((column) => (
              <th
                scope="col"
                key={column.key}
                title={`${column.name}: ${column.help}`}
              >
                {column.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {guesses.map((guess) => (
            <tr key={guess.item}>
              <th scope="row">
                <ItemName guess={guess} />
              </th>
              {COLUMNS.map((column) => {
                const feedback = guess.feedback[column.key];
                return (
                  <td
                    key={column.key}
                    className={`clue is-${feedback.match}`}
                    tabIndex={0}
                    aria-label={describe(column, guess)}
                  >
                    <span aria-hidden="true">
                      {cell(column.key, guess.values)} {arrowText(feedback)}
                    </span>
                    <span className="clue-tip" aria-hidden="true">
                      <strong>
                        {column.name}: {full(column.key, guess.values)}
                      </strong>
                      {hint(column.key, feedback)}
                    </span>
                  </td>
                );
              })}
            </tr>
          ))}
          {Array.from(
            { length: Math.max(0, limit - guesses.length) },
            (_, row) => (
              <tr key={`empty-${row}`} className="is-empty" aria-hidden="true">
                <td />
                {COLUMNS.map((column) => (
                  <td key={column.key} />
                ))}
              </tr>
            ),
          )}
        </tbody>
      </table>
    </div>
  );
}

function KnownPanel({ guesses }: Readonly<{ guesses: readonly Guess[] }>) {
  return (
    <section className="curator-known" aria-labelledby="curator-known-title">
      <h3 id="curator-known-title" className="quiet-label">
        What you know
      </h3>
      <dl>
        {COLUMNS.map((column) => {
          const fact = known(guesses, column.key);
          return (
            <div key={column.key} className={`is-${fact.state}`}>
              <dt>{column.label}</dt>
              <dd>{fact.text}</dd>
            </div>
          );
        })}
      </dl>
    </section>
  );
}

function GuessList({ guesses }: Readonly<{ guesses: readonly Guess[] }>) {
  // The newest guess opens on its own; a choice lasts until the next guess.
  const newest = guesses.at(-1)?.item;
  const [choice, setChoice] = useState<{
    newest?: string;
    open: string;
  } | null>(null);
  const expanded = choice?.newest === newest ? choice?.open : newest;
  const setOpen = (open: string) => setChoice({ newest, open });
  if (guesses.length === 0) return null;
  return (
    <ol
      className="curator-list"
      reversed
      aria-label="Your guesses, newest first"
    >
      {[...guesses].reverse().map((guess) => {
        const isOpen = guess.item === expanded;
        return (
          <li key={guess.item} className={isOpen ? "is-open" : undefined}>
            <button
              type="button"
              aria-expanded={isOpen}
              onClick={() => setOpen(isOpen ? "" : guess.item)}
            >
              <ItemName guess={guess} />
              <span className="curator-strip" aria-hidden="true">
                {COLUMNS.map((column) => (
                  <i
                    key={column.key}
                    className={`is-${guess.feedback[column.key].match}`}
                  />
                ))}
              </span>
            </button>
            {isOpen && (
              <ul className="curator-clues">
                {COLUMNS.map((column) => {
                  const feedback = guess.feedback[column.key];
                  return (
                    <li key={column.key} className={`is-${feedback.match}`}>
                      <span className="sr-only">{describe(column, guess)}</span>
                      <span aria-hidden="true">
                        {column.label} {cell(column.key, guess.values)}{" "}
                        {arrowText(feedback)}
                      </span>
                    </li>
                  );
                })}
              </ul>
            )}
          </li>
        );
      })}
    </ol>
  );
}

function Result({ today, next }: Readonly<{ today: Playing; next: string }>) {
  const [copied, setCopied] = useState(false);
  const answer = today.answer;
  const stats = today.stats;
  const solved = today.state === "solved";
  useEffect(() => {
    if (!copied) return;
    const timer = setTimeout(() => setCopied(false), 2000);
    return () => clearTimeout(timer);
  }, [copied]);
  const copy = () => {
    void navigator.clipboard
      ?.writeText(share(today.number, today.guesses, solved, today.limit))
      .then(() => setCopied(true));
  };
  return (
    <section className="curator-result" aria-label="Today’s answer">
      {answer && (
        <div className="curator-answer">
          <Icon item={answer.item} collapse />
          <div>
            <p
              className="curator-answer-name"
              style={{ color: RARITY_COLOUR[answer.values.rarity ?? ""] }}
            >
              {answer.name}
            </p>
            <p className="quiet-label">
              {[answer.values.rarity, answer.values.type]
                .filter(Boolean)
                .join(" ")
                .replaceAll("_", " ")}
            </p>
          </div>
        </div>
      )}
      <p className={solved ? "curator-solved" : "curator-failed"}>
        {solved
          ? `Solved in ${today.guesses.length} of ${today.limit}`
          : `Not solved in ${today.limit} guesses`}
      </p>
      {stats && (
        <>
          <p>
            Streak {stats.streak} · Best {stats.best_streak}
          </p>
          <p>
            Played {stats.played} · Solved{" "}
            {stats.played ? Math.round((stats.solved / stats.played) * 100) : 0}
            %
          </p>
        </>
      )}
      <div className="curator-result-actions">
        <button type="button" onClick={copy}>
          {copied ? "Copied" : "Copy result"}
        </button>
        <span className="quiet-label">New item in {next}</span>
      </div>
    </section>
  );
}

function month(season: string, offset = 0) {
  const [year = 1970, number = 1] = season.split("-").map(Number);
  return new Date(Date.UTC(year, number - 1 + offset, 1)).toLocaleString(
    "en-US",
    {
      month: "long",
      timeZone: "UTC",
    },
  );
}

function LeaderboardView() {
  const [board, setBoard] = useState<Leaderboard | null>(null);
  const [error, setError] = useState("");
  const load = useCallback(() => {
    getLeaderboard()
      .then((value) => {
        setBoard(value);
        setError("");
      })
      .catch((problem: unknown) =>
        setError(
          problem instanceof CuratorError
            ? problem.message
            : "Something went wrong. Try again.",
        ),
      );
  }, []);
  useEffect(() => {
    load();
    const timer = setInterval(() => {
      if (document.visibilityState === "visible") load();
    }, 60_000);
    return () => clearInterval(timer);
  }, [load]);
  useReturnRefresh(load);

  if (!board)
    return error ? (
      <p role="alert">{error}</p>
    ) : (
      <p className="quiet-label">Loading the leaderboard…</p>
    );
  const rows = board.you ? [...board.top, board.you] : board.top;
  return (
    <section className="curator-board" aria-labelledby="curator-season">
      <div className="curator-round-head">
        <h2 id="curator-season">{month(board.season)} season</h2>
        <span className="quiet-label">
          day {board.day} of {board.days}
        </span>
      </div>
      <div className="curator-board-body">
        {board.top.length === 0 ? (
          <p className="quiet-label">No finished rounds yet this season</p>
        ) : (
          <div className="detail-table-wrap">
            <table className="detail-table curator-standings">
              <thead>
                <tr>
                  <th scope="col">#</th>
                  <th scope="col">Player</th>
                  <th scope="col">Points</th>
                  <th scope="col">Solved</th>
                  <th scope="col">Streak</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr
                    key={`${row.rank}-${row.name}`}
                    className={`${row.you ? "is-you" : ""}${row === board.you ? " is-pinned" : ""}`}
                  >
                    <td>{row.rank}</td>
                    <td>{row.name}</td>
                    <td>{row.points}</td>
                    <td>
                      {row.solved}/{row.played}
                    </td>
                    <td>{row.streak}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {board.stats ? (
          <Season stats={board.stats} players={board.players} />
        ) : (
          <p className="quiet-label curator-board-note">
            <a href="/link">Link your Minecraft account</a> to see your own
            standing.
          </p>
        )}
      </div>
      {error && <p role="alert">{error}</p>}
      <p className="quiet-label">
        Season ends {month(board.season, 1)} 1 · standings update after every
        finished round
      </p>
    </section>
  );
}

function Season({
  stats,
  players,
}: Readonly<{ stats: NonNullable<Leaderboard["stats"]>; players: number }>) {
  const most = Math.max(1, ...stats.histogram);
  return (
    <section className="curator-season" aria-labelledby="curator-yours">
      <h3 id="curator-yours">Your season</h3>
      <p>
        {stats.rank
          ? `Rank ${stats.rank} of ${players}`
          : "No finished rounds yet"}
      </p>
      <p className="quiet-label">
        {stats.points} points · {stats.solved} of {stats.played} solved
      </p>
      <p className="quiet-label">
        Streak {stats.streak} · Best {stats.best_streak}
        {stats.average === null ? "" : ` · Average ${stats.average} guesses`}
      </p>
      <h4 className="quiet-label">Guesses per solve</h4>
      <ol className="curator-histogram">
        {stats.histogram.map((count, index) => (
          <li key={index} aria-label={`${index + 1} guesses: ${count}`}>
            <span aria-hidden="true">{index + 1}</span>
            <i
              aria-hidden="true"
              style={{ width: `${(count / most) * 100}%` }}
            />
            <span aria-hidden="true">{count}</span>
          </li>
        ))}
      </ol>
      {stats.failed > 0 && (
        <p className="quiet-label">Not solved: {stats.failed}</p>
      )}
    </section>
  );
}
