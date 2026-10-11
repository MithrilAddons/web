import { useCallback, useEffect, useState } from "react";
import "./moderation.css";

type Account = {
  roles: string[];
  codes: { id: string; created: number; last_used: number | null }[];
};

async function call<T>(path: string, body?: object): Promise<T> {
  const response = await fetch(`/api/v1/capture/${path}`, {
    method: body ? "POST" : "GET",
    credentials: "same-origin",
    cache: "no-store",
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify({ version: 1, ...body }) : undefined,
  });
  if (!response.ok) {
    let detail = "Something went wrong. Try again.";
    try {
      const value = (await response.json()) as { detail?: unknown };
      if (typeof value.detail === "string") detail = value.detail;
    } catch {
      // Keep the generic message for a body that isn't JSON.
    }
    throw Object.assign(new Error(detail), { status: response.status });
  }
  return response.json() as Promise<T>;
}

function when(seconds: number | null) {
  return seconds === null ? "Never" : new Date(seconds * 1000).toLocaleString();
}

/** Upload codes for the private capture mod; only people with the Capturer role can make them. */
export function Capture() {
  const [account, setAccount] = useState<Account | null>(null);
  const [signedOut, setSignedOut] = useState(false);
  const [code, setCode] = useState("");
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      setAccount(await call<Account>("account"));
    } catch (err) {
      if ((err as { status?: number }).status === 401) setSignedOut(true);
      else setError((err as Error).message);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function act(action: () => Promise<void>) {
    setBusy(true);
    setError("");
    try {
      await action();
      await load();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="content-stack capture-page">
      <title>Capture · Mithril</title>
      <h1>Capture</h1>
      <p>
        Upload codes connect the Mithril Capture mod to your account, so the
        maps and locations you capture reach the review queue.
      </p>
      {signedOut && (
        <p>
          <a href="/link">Link your Minecraft account</a> first, then come back
          here.
        </p>
      )}
      {error && <p role="alert">{error}</p>}
      {account && !account.roles.includes("capturer") && (
        <p>
          You don’t have the Capturer role yet. Ask the owner to add you, then
          reload this page.
        </p>
      )}
      {account?.roles.includes("capturer") && (
        <>
          {code ? (
            <div className="capture-code" role="status">
              <p>
                Paste this code into the capture mod’s welcome screen. It won’t
                be shown again.
              </p>
              <code>{code}</code>
              <button
                type="button"
                className="secondary"
                onClick={() =>
                  void navigator.clipboard
                    ?.writeText(code)
                    .then(() => setCopied(true))
                }
              >
                {copied ? "Copied" : "Copy code"}
              </button>
            </div>
          ) : (
            <button
              type="button"
              className="primary"
              disabled={busy}
              onClick={() =>
                void act(async () => {
                  const created = await call<{ code: string }>("codes", {});
                  setCode(created.code);
                  setCopied(false);
                })
              }
            >
              Create upload code
            </button>
          )}
          <h2>Your upload codes</h2>
          {account.codes.length ? (
            <div className="detail-table-wrap">
              <table className="detail-table">
                <thead>
                  <tr>
                    <th scope="col">Created</th>
                    <th scope="col">Last used</th>
                    <th scope="col">
                      <span className="sr-only">Actions</span>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {account.codes.map((item) => (
                    <tr key={item.id}>
                      <td>{when(item.created)}</td>
                      <td>{when(item.last_used)}</td>
                      <td>
                        <button
                          type="button"
                          className="secondary"
                          disabled={busy}
                          onClick={() =>
                            void act(async () => {
                              await call("codes/revoke", { id: item.id });
                            })
                          }
                        >
                          Revoke
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="quiet-label">No upload codes yet.</p>
          )}
        </>
      )}
    </section>
  );
}
