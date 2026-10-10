import { useEffect, useState } from "react";

const releases = "https://github.com/MithrilAddons/mithrilpf/releases";
type Release = { version: string; url: string };

export function ModDownload() {
  const [release, setRelease] = useState<Release | null>(null);
  const [status, setStatus] = useState("Checking the latest release…");
  useEffect(() => {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 8000);
    let active = true;
    void fetch("/api/v1/mod-release", {
      signal: controller.signal,
      credentials: "omit",
    })
      .then(async (response) => {
        if (!response.ok) throw new Error("Release unavailable");
        const data = await response.json();
        if (!active) return;
        const next = data.release;
        if (
          data.status === "ready" &&
          next &&
          typeof next.version === "string" &&
          /^\d+\.\d+\.\d+(?:-(?:alpha|beta|rc)\.\d+)?$/.test(next.version) &&
          next.url ===
            `${releases}/download/v${next.version}/mithrilpf-${next.version}.jar`
        ) {
          setRelease(next);
          setStatus("");
        } else {
          setStatus(
            data.status === "none"
              ? "No public release yet."
              : "Check GitHub for downloads.",
          );
        }
      })
      .catch(() => {
        if (active) setStatus("Check GitHub for downloads.");
      })
      .finally(() => clearTimeout(timeout));
    return () => {
      active = false;
      clearTimeout(timeout);
      controller.abort();
    };
  }, []);
  return (
    <div className="mod-download">
      {release ? (
        <>
          <a className="button primary" href={release.url}>
            Download mod{" "}
            <span className="small">
              v{release.version}
              {release.version.includes("-") ? " · Beta" : ""} · JAR
            </span>
          </a>
          <a href={releases}>Release notes</a>
        </>
      ) : (
        <>
          <a className="button" href={releases}>
            View releases
          </a>
          <output className="quiet-label">{status}</output>
        </>
      )}
    </div>
  );
}
