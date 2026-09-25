import { useEffect, useState } from "react";
import { getHealth } from "./api";
import { Account, CookiePolicy, LinkAccount } from "./account";

// Remove the bearer secret before React renders (including StrictMode remounts).
const linkToken =
  window.location.pathname.replace(/\/+$/, "") === "/link"
    ? window.location.hash.slice(1)
    : "";
if (linkToken) window.history.replaceState(null, "", "/link");

export function App() {
  const path = window.location.pathname.replace(/\/+$/, "") || "/";
  const isPartyFinder = path === "/party-finder";

  return (
    <>
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <header className="site-header">
        <a className="brand" href="/">
          <svg
            className="brand-mark"
            viewBox="0 0 24 24"
            fill="none"
            aria-hidden="true"
          >
            <path
              d="M3 18V6l9 8 9-8v12M7 18v-4l5 4 5-4v4"
              stroke="currentColor"
              strokeWidth="1.7"
              strokeLinejoin="round"
            />
          </svg>
          Mithril{isPartyFinder && <span>PF</span>}
        </a>
        <nav aria-label="Main navigation">
          <a
            href="/party-finder"
            aria-current={isPartyFinder ? "page" : undefined}
          >
            Party finder
          </a>
        </nav>
      </header>
      <main
        id="main"
        tabIndex={-1}
        className={
          isPartyFinder
            ? "workspace-page"
            : path === "/"
              ? "home-page"
              : "content-page"
        }
      >
        {isPartyFinder ? (
          <PartyFinder />
        ) : path === "/link" ? (
          <div className="link-panel">
            <LinkAccount token={linkToken} />
          </div>
        ) : path === "/cookies" ? (
          <CookiePolicy />
        ) : path === "/" ? (
          <>
            <title>Mithril</title>
            <section className="hero">
              <h1>Party Finder</h1>
              <div className="hero-actions">
                <a className="button primary" href="/party-finder">
                  Open party finder <span aria-hidden="true">→</span>
                </a>
                <span className="quiet-label">In development</span>
              </div>
            </section>
            <section className="intro-details" aria-label="Account linking">
              <div>
                <span className="detail-number" aria-hidden="true">
                  01
                </span>
                <h2>Start in Minecraft</h2>
                <p>
                  Open <code>/mithrilpf</code> and link your account.
                </p>
              </div>
              <div>
                <span className="detail-number" aria-hidden="true">
                  02
                </span>
                <h2>Continue in your browser</h2>
                <p>Confirm once. Choose to stay signed in.</p>
              </div>
            </section>
          </>
        ) : (
          <>
            <title>Page not found · Mithril</title>
            <h1>Page not found</h1>
            <a href="/">Home</a>
          </>
        )}
      </main>
      <footer className="site-footer">
        <p>Not affiliated with Hypixel or Mojang.</p>
        <a href="/cookies">Cookies</a>
      </footer>
    </>
  );
}

function PartyFinder() {
  const [status, setStatus] = useState("Checking service…");

  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    const deadline = setTimeout(() => controller.abort(), 5000);
    void getHealth(controller.signal)
      .then(() => {
        if (active) setStatus("Service online");
      })
      .catch(() => {
        if (active) setStatus("Service unavailable");
      })
      .finally(() => clearTimeout(deadline));
    return () => {
      active = false;
      clearTimeout(deadline);
      controller.abort();
    };
  }, []);

  return (
    <>
      <title>MithrilPF · Party finder</title>
      <div className="page-heading">
        <div>
          <h1>Dungeon party finder</h1>
        </div>
        <p
          className="status"
          data-state={
            status === "Service online"
              ? "online"
              : status === "Service unavailable"
                ? "offline"
                : "pending"
          }
          role="status"
        >
          {status}
        </p>
      </div>
      <div className="workspace">
        <section className="party-panel" aria-labelledby="parties-heading">
          <div className="panel-toolbar">
            <h2 id="parties-heading">Parties</h2>
            <span className="tag">In development.</span>
          </div>
          <div className="empty-state">
            <svg viewBox="0 0 48 48" fill="none" aria-hidden="true">
              <rect x="8" y="8" width="13" height="13" rx="3" />
              <rect x="27" y="8" width="13" height="13" rx="3" />
              <rect x="8" y="27" width="13" height="13" rx="3" />
              <rect x="27" y="27" width="13" height="13" rx="3" />
            </svg>
            <h3>Not quite ready yet.</h3>
            <p>Party browsing and matching are coming next.</p>
          </div>
        </section>
        <aside className="account-panel">
          <h2>Your account</h2>
          <Account />
        </aside>
      </div>
    </>
  );
}
