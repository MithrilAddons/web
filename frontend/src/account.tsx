import { useEffect, useRef, useState } from "react";
import { SkinPreview } from "./SkinPreview";
import { PlayerCard } from "./PlayerCard";

type User = { uuid: string; name: string };
type Session = { authenticated: boolean; user?: User };

async function request<T>(path: string, body?: object): Promise<T> {
  const response = await fetch(`/api/v1/auth/${path}`, {
    method: body ? "POST" : "GET",
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
    credentials: "same-origin",
    cache: "no-store",
    signal: AbortSignal.timeout(10000),
  });
  if (!response.ok) throw new Error("Request failed");
  return response.json() as Promise<T>;
}

export function Account() {
  const [cardOpen, setCardOpen] = useState(false);
  const nameButton = useRef<HTMLButtonElement>(null);
  const [session, setSession] = useState<Session | null>(null);
  const [error, setError] = useState(false);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    let active = true;
    void request<Session>("session").then(
      (value) => {
        if (active) setSession(value);
      },
      () => {
        if (active) setError(true);
      },
    );
    return () => {
      active = false;
    };
  }, []);
  async function logout() {
    setBusy(true);
    setError(false);
    try {
      setSession(await request<Session>("logout", {}));
    } catch {
      setError(true);
    } finally {
      setBusy(false);
    }
  }
  return (
    <section aria-label="Account">
      {session?.authenticated && session.user ? (
        <div className="signed-in">
          <div className="account-identity">
            <span className="avatar" aria-hidden="true">
              {session.user.name.slice(0, 1)}
            </span>
            <div>
              <button
                ref={nameButton}
                className="account-name"
                aria-haspopup="dialog"
                onClick={() => setCardOpen(true)}
              >
                {session.user.name}
              </button>
              <span className="quiet-label">Minecraft account</span>
            </div>
          </div>
          <SkinPreview key={session.user.uuid} name={session.user.name} />
          {cardOpen && (
            <PlayerCard
              key={`card-${session.user.uuid}`}
              user={session.user}
              onClose={() => {
                setCardOpen(false);
                nameButton.current?.focus();
              }}
            />
          )}
          <button
            className="secondary"
            disabled={busy}
            onClick={() => void logout()}
          >
            Log out
          </button>
        </div>
      ) : session ? (
        <div className="sign-in-help">
          <p>Link your Minecraft account to sign in.</p>
          <ol>
            <li>
              Open <code>/mithrilpf</code> in game.
            </li>
            <li>
              Select <strong>Link browser</strong>.
            </li>
          </ol>
        </div>
      ) : !error ? (
        <p className="quiet-label">Checking account…</p>
      ) : null}
      {error && <p role="alert">Account service unavailable. Try again.</p>}
    </section>
  );
}

export function LinkAccount({ token }: { token: string }) {
  const [user, setUser] = useState<User | null>(null);
  const [remember, setRemember] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [done, setDone] = useState(false);
  useEffect(() => {
    let active = true;
    if (!/^[A-Za-z0-9_-]{43}$/.test(token)) return;
    void request<User>("preview", { token }).then(
      (value) => {
        if (active) setUser(value);
      },
      () => {
        if (active)
          setError("Link unavailable or expired. Create another in Minecraft.");
      },
    );
    return () => {
      active = false;
    };
  }, [token]);
  async function complete() {
    setBusy(true);
    setError("");
    try {
      await request<Session>("complete", { token, remember });
      setDone(true);
    } catch {
      setError("Could not sign in. Create another link in Minecraft.");
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <title>Link account · Mithril</title>
      <h1>Link account</h1>
      {done ? (
        <>
          <p role="status">Signed in as {user?.name}.</p>
          <a className="button primary" href="/party-finder">
            Party finder <span aria-hidden="true">→</span>
          </a>
        </>
      ) : (
        <>
          {!/^[A-Za-z0-9_-]{43}$/.test(token) ? (
            <p>Open Link browser in Minecraft to create a new link.</p>
          ) : user ? (
            <>
              <p>
                Only continue if you created this link in your own Minecraft
                client.
              </p>
              <label className="remember">
                <input
                  type="checkbox"
                  checked={remember}
                  onChange={(event) => setRemember(event.target.checked)}
                />{" "}
                Remember this browser for 30 days
              </label>
              <p>
                Signing in uses a necessary session cookie. Remembering this
                browser saves it between visits.{" "}
                <a href="/cookies" target="_blank" rel="noreferrer">
                  Cookie policy
                </a>
              </p>
              <button
                className="primary"
                disabled={busy}
                onClick={() => void complete()}
              >
                Continue as {user.name}
              </button>
            </>
          ) : (
            !error && <p role="status">Checking link…</p>
          )}
          {error && <p role="alert">{error}</p>}
        </>
      )}
    </>
  );
}

export function CookiePolicy() {
  return (
    <article>
      <title>Cookie policy · Mithril</title>
      <h1>Cookie policy</h1>
      <p>Updated 26 September 2026.</p>
      <p>
        Browsing Mithril without signing in sets no cookies. We do not use
        analytics, advertising cookies, or third-party trackers.
      </p>
      <h2>Sign-in cookie</h2>
      <p>
        <code>__Host-mithril_session</code> keeps you signed in. It contains a
        random identifier, not your Minecraft credentials. It is sent only over
        HTTPS, cannot be read by page scripts, and is restricted to this site.
      </p>
      <p>
        Without “Remember this browser”, it is a browser-session cookie and the
        server session expires after 24 hours. Some browsers restore session
        cookies when restoring open tabs.
      </p>
      <p>
        If you choose “Remember this browser”, it lasts up to 30 days and renews
        when you return after at least a day. You can leave this option off.
      </p>
      <h2>Removing it</h2>
      <p>
        Use Log out on the party-finder page to revoke this browser’s session
        and remove its cookie. You can also clear this site’s cookies in your
        browser; this signs you out locally. Blocking cookies prevents sign-in
        but does not prevent browsing.
      </p>
      <h2>Account data</h2>
      <p>
        We verify account ownership with Mojang and store your Minecraft UUID,
        username, a hash of the session identifier, and its expiry. Minecraft
        access tokens are never sent to this website. Verification challenges
        expire after one minute and unused sign-in links after five minutes.
        Expired records are removed during authentication activity or within an
        hour while the service is running.
      </p>
      <p>
        The mod can save a per-account link-status reference in its instance
        configuration. Our server stores its hash and associates it with your
        browser session after confirmation. It can check whether that session is
        still linked, but cannot sign in or renew it. It expires with the
        session and is revoked when you log out; it sets no additional cookie.
      </p>
      <p>
        Your skin preview is fetched by our server from Mojang and Minecraft’s
        texture servers and cached temporarily in memory. Your browser contacts
        only Mithril for this preview; no extra cookie is used.
      </p>
      <p>
        Opening your player card fetches your selected SkyBlock profile from
        Hypixel. Dungeon stats are cached in server memory for up to five
        minutes; no extra cookie is used.
      </p>
      <p>
        A linked MithrilPF mod syncs your account-wide solo-clear and terminal
        personal bests after a separate Minecraft ownership check. We store
        these timings with your UUID so they remain available while you are
        offline. No full run history or Minecraft access token is uploaded.
        Logging out stops uploads through that browser link but does not erase
        previously saved records.
      </p>
    </article>
  );
}
