import { useEffect, useState } from "react";
import { getHealth } from "./api";
import { CookiePolicy, LinkAccount } from "./account";
import { PartyWorkspace } from "./PartyFinder";
import { AccountPrivacy, PrivacyPolicy } from "./Privacy";
import { Moderation } from "./Moderation";
import { SlayerProfits } from "./SlayerProfits";

// Remove the bearer secret before React renders (including StrictMode remounts).
const linkToken =
  window.location.pathname.replace(/\/+$/, "") === "/link"
    ? window.location.hash.slice(1)
    : "";
if (linkToken) window.history.replaceState(null, "", "/link");

export function App() {
  const revision = import.meta.env.VITE_SOURCE_REVISION as string | undefined;
  const sourceRef =
    revision && /^[0-9a-f]{40}$/.test(revision) ? revision : "main";
  const sourceUrl = "https://github.com/MithrilAddons/web";
  const path = window.location.pathname.replace(/\/+$/, "") || "/";
  const isPartyFinder = path === "/party-finder";
  const isSlayerProfits =
    path === "/slayer-profits" || path === "/slayerprofits";

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
          <a
            href="/slayer-profits"
            aria-current={isSlayerProfits ? "page" : undefined}
          >
            Slayer profits
          </a>
        </nav>
      </header>
      <main
        id="main"
        tabIndex={-1}
        className={pageClass(path, isPartyFinder || isSlayerProfits)}
      >
        <PageContent path={path} />
      </main>
      <footer className="site-footer">
        <p>Not affiliated with Hypixel or Mojang.</p>
        <a href="/cookies">Cookies</a>
        <a href="/privacy">Privacy</a>
        <a
          href={
            sourceRef === "main" ? sourceUrl : `${sourceUrl}/tree/${sourceRef}`
          }
        >
          Source code
        </a>
        <a href={`${sourceUrl}/blob/${sourceRef}/LICENSE`}>AGPL-3.0</a>
      </footer>
    </>
  );
}

function pageClass(path: string, workspace: boolean) {
  if (workspace) return "workspace-page";
  return path === "/" ? "home-page" : "content-page";
}

function PageContent({ path }: Readonly<{ path: string }>) {
  switch (path) {
    case "/party-finder":
      return <PartyFinder />;
    case "/slayer-profits":
    case "/slayerprofits":
      return <SlayerProfits />;
    case "/privacy":
      return <PrivacyPolicy />;
    case "/account":
      return <AccountPrivacy />;
    case "/moderation":
      return <Moderation />;
    case "/link":
      return (
        <div className="link-panel">
          <LinkAccount token={linkToken} />
        </div>
      );
    case "/cookies":
      return <CookiePolicy />;
    case "/":
      return (
        <>
          <title>Mithril</title>
          <section className="hero">
            <h1>Party Finder</h1>
            <div className="hero-actions">
              <a className="button primary" href="/party-finder">
                Open party finder <span aria-hidden="true">→</span>
              </a>
              <span className="quiet-label">In development</span>
              <a href="/slayer-profits">Calculate Slayer profits</a>
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
      );
    default:
      return (
        <>
          <title>Page not found · Mithril</title>
          <h1>Page not found</h1>
          <a href="/">Home</a>
        </>
      );
  }
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
      <PartyWorkspace />
    </>
  );
}
