import { useEffect, useRef, useState } from "react";

export function PrivacyPolicy() {
  const [contact, setContact] = useState<{
    operator: string;
    email: string;
  } | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    void fetch("/api/v1/privacy", {
      signal: controller.signal,
      cache: "no-store",
    })
      .then(async (response) => {
        if (response.ok)
          setContact(
            (await response.json()) as { operator: string; email: string },
          );
      })
      .catch(() => undefined);
    return () => controller.abort();
  }, []);
  return (
    <article>
      <h1>Privacy</h1>
      <p>
        MithrilPF stores your Minecraft UUID and username, browser links,
        submitted records and the evidence needed to validate them. Party
        members can see party chat and player stats. Trusted moderators can
        review reported messages, records and restrictions.
      </p>
      <p>
        We use account and gameplay data to provide party finding and record
        validation. We use limited moderation and connection data to prevent
        abuse, handle appeals and hold moderators accountable. We do not sell
        personal data or use advertising trackers.
      </p>
      <h2>Retention</h2>
      <ul>
        <li>PB summaries: until you delete them.</li>
        <li>
          Accepted soloclear and terminal evidence: 30 days. Rejected or
          abandoned attempts: 7 days.
        </li>
        <li>
          Ordinary party chat: temporary, up to 100 messages per party. Reported
          messages: 30 days unless needed for a restriction or appeal.
        </li>
        <li>
          Evidence attached to a temporary restriction: until it ends. Permanent
          restrictions: 30 days of detailed evidence. An open appeal extends
          retention until the appeal closes.
        </li>
        <li>
          Minimal restriction and moderator-action history: 180 days after the
          case ends. Active restrictions and open appeals remain on record.
        </li>
        <li>
          Recent authenticated connection associations: 24 hours. IP bans retain
          a keyed address fingerprint while active; moderators cannot see IP
          addresses.
        </li>
        <li>
          Backups and the separate deletion-recovery ledger: up to 7 days.
          Deletions are reapplied before restored data is served.
        </li>
      </ul>
      <h2>Your data</h2>
      <p>
        <a href="/account">Delete your synced PBs or account</a>. Account
        deletion removes browser links and unneeded data. Active restrictions,
        open investigations, appeal evidence and the limited audit history above
        may remain. Deleting an account does not remove a ban. Local records in
        Minecraft remain on your device.
      </p>
      <p>
        You can request access, correction, deletion, restriction or portability
        of your data, and object to processing based on legitimate interests.
        You may also complain to your data-protection authority.
      </p>
      <h2>Contact</h2>
      {contact ? (
        <p>
          {contact.operator} ·{" "}
          <a href={`mailto:${contact.email}`}>{contact.email}</a>
        </p>
      ) : (
        <p>Privacy contact is not configured yet.</p>
      )}
      <p>
        Hypixel and Mojang receive requests needed to verify Minecraft ownership
        and retrieve game stats. Their services apply their own privacy
        policies.
      </p>
    </article>
  );
}

export function AccountPrivacy() {
  const [user, setUser] = useState<{ uuid: string; name: string } | null>(null);
  const [ready, setReady] = useState(false);
  const [scope, setScope] = useState("records");
  const [confirmation, setConfirmation] = useState("");
  const [busy, setBusy] = useState(false);
  const working = useRef(false);
  const [status, setStatus] = useState("");
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    void fetch("/api/v1/auth/session", {
      credentials: "same-origin",
      cache: "no-store",
      signal: AbortSignal.timeout(10000),
    })
      .then(async (response) => {
        if (!response.ok) throw new Error("Could not check your account.");
        const value = (await response.json()) as {
          authenticated: boolean;
          user?: { uuid: string; name: string };
        };
        if (active) {
          setUser(value.authenticated ? (value.user ?? null) : null);
          setReady(true);
        }
      })
      .catch(() => {
        if (active)
          setError("Could not check your account. Reload to try again.");
      });
    return () => {
      active = false;
    };
  }, []);
  async function erase() {
    if (working.current || confirmation !== "DELETE") return;
    working.current = true;
    setBusy(true);
    setError("");
    setStatus("");
    try {
      const response = await fetch("/api/v1/auth/erase", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ version: 1, scope, confirmation }),
        signal: AbortSignal.timeout(15000),
      });
      if (!response.ok)
        throw new Error(
          "Deletion failed. Reload your account before trying again.",
        );
      setStatus(
        scope === "account"
          ? "Account deleted. You are signed out."
          : "Synced PBs deleted.",
      );
      if (scope === "account") setUser(null);
      setConfirmation("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Deletion failed.");
    } finally {
      working.current = false;
      setBusy(false);
    }
  }
  return (
    <section className="moderation">
      <h1>Your data</h1>
      {error && <p role="alert">{error}</p>}
      {status && <output>{status}</output>}
      {!ready && !error && <p>Checking your account…</p>}
      {ready && !user && !status && (
        <p>
          <a href="/party-finder">Sign in with your Minecraft account</a> to
          manage your data.
        </p>
      )}
      {user && (
        <form
          className="privacy-form"
          onSubmit={(event) => {
            event.preventDefault();
            void erase();
          }}
        >
          <h2>{user.name}</h2>
          <label>
            Delete{" "}
            <select
              value={scope}
              disabled={busy}
              onChange={(e) => {
                setScope(e.target.value);
                setConfirmation("");
              }}
            >
              <option value="records">Synced PBs</option>
              <option value="account">Account and synced PBs</option>
            </select>
          </label>
          <p>
            {scope === "account"
              ? "Deletes browser links and signs out every linked client."
              : "Removes your synced PBs from party requirements."}{" "}
            Local Minecraft records remain. Active restrictions and required
            review evidence follow the <a href="/privacy">retention policy</a>.
          </p>
          <label>
            Type DELETE to confirm{" "}
            <input
              value={confirmation}
              disabled={busy}
              onChange={(e) => setConfirmation(e.target.value)}
              autoComplete="off"
            />
          </label>
          <button type="submit" disabled={busy || confirmation !== "DELETE"}>
            {busy ? "Deleting…" : "Delete selected data"}
          </button>
        </form>
      )}
    </section>
  );
}
