import { useEffect, useState } from "react";
import { getLeaderboard, type Leaderboard, type Ranked } from "./locationsApi";
import { message } from "./locationsShared";

function monthName(season: string) {
  const [year, month] = season.split("-").map(Number);
  return new Date(Date.UTC(year!, month! - 1, 1)).toLocaleString("en-US", {
    month: "long",
    year: "numeric",
    timeZone: "UTC",
  });
}

function Row({ row }: Readonly<{ row: Ranked }>) {
  return (
    <tr aria-current={row.you ? "true" : undefined}>
      <td>{row.rank}</td>
      <td>{row.name}</td>
      <td>{row.rating}</td>
      <td>
        {row.wins}–{row.losses}–{row.draws}
      </td>
      <td>{row.peak}</td>
    </tr>
  );
}

/** The season's established duellists by rating, and each past season's final top 10. */
export function DuelBoard() {
  const [board, setBoard] = useState<Leaderboard | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    getLeaderboard()
      .then(setBoard)
      .catch((error_: unknown) => setError(message(error_)));
  }, []);
  if (error) return <p role="alert">{error}</p>;
  if (!board) return <p className="quiet-label">Loading the leaderboard…</p>;
  return (
    <section className="curator-board">
      <h2>{monthName(board.season)} season</h2>
      {board.top.length ? (
        <div className="detail-table-wrap">
          <table className="detail-table">
            <thead>
              <tr>
                <th scope="col">#</th>
                <th scope="col">Player</th>
                <th scope="col">Rating</th>
                <th scope="col">W–L–D</th>
                <th scope="col">Peak</th>
              </tr>
            </thead>
            <tbody>
              {board.top.map((row) => (
                <Row key={row.rank} row={row} />
              ))}
              {board.you && <Row row={board.you} />}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="quiet-label">
          Nobody has an established rating this season yet.
        </p>
      )}
      <p className="quiet-label">
        Players appear once their rating settles, after a few duels. Each month
        ratings move a quarter of the way back to 1500.
      </p>
      {board.past.map((season) => (
        <details key={season.season}>
          <summary>{monthName(season.season)}</summary>
          <ol>
            {season.top.map((row) => (
              <li key={row.rank}>
                {row.name} · {row.rating}
              </li>
            ))}
          </ol>
        </details>
      ))}
    </section>
  );
}
