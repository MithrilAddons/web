import { useEffect, useState } from "react";

type Device = { id: string; name: string; expires: number };

export function MinecraftSessions() {
  const [devices, setDevices] = useState<Device[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [revision, setRevision] = useState(0);
  const [ready, setReady] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    setReady(false);
    void fetch("/api/v1/auth/devices", {
      credentials: "same-origin",
      cache: "no-store",
      signal: AbortSignal.any([controller.signal, AbortSignal.timeout(10000)]),
    })
      .then(async (response) => {
        if (!response.ok) throw new Error("Could not load Minecraft sessions.");
        const data = (await response.json()) as { devices: Device[] };
        if (!Array.isArray(data.devices))
          throw new Error("Could not load Minecraft sessions.");
        if (!controller.signal.aborted) {
          setDevices(data.devices);
          setReady(true);
          setError("");
        }
      })
      .catch(() => {
        if (!controller.signal.aborted)
          setError("Could not load Minecraft sessions.");
      });
    return () => controller.abort();
  }, [revision]);

  async function revoke(id: string) {
    setBusy(true);
    setError("");
    try {
      const response = await fetch("/api/v1/auth/devices/revoke", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id }),
        signal: AbortSignal.timeout(10000),
      });
      if (!response.ok)
        throw new Error("Could not revoke this session. Try again.");
      setDevices((current) => current.filter((device) => device.id !== id));
    } catch {
      setError("Could not revoke this session. Try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="content-stack" aria-label="Minecraft sessions">
      <h2>Minecraft sessions</h2>
      <p>
        Signing out here disconnects that mod instance. Your browser stays
        signed in.
      </p>
      {error && <p role="alert">{error}</p>}
      {!ready && !error && <p>Loading sessions…</p>}
      {ready && devices.length === 0 && <p>No Minecraft sessions.</p>}
      {devices.map((device, index) => (
        <div className="panel content-stack" key={device.id}>
          <span>
            Session {index + 1} · {device.name} · expires{" "}
            {new Date(device.expires * 1000).toLocaleDateString()}
          </span>
          <button
            disabled={busy}
            onClick={() => void revoke(device.id)}
            aria-label={`Sign out Minecraft session ${index + 1}`}
          >
            Sign out
          </button>
        </div>
      ))}
      <button
        disabled={busy}
        onClick={() => setRevision((current) => current + 1)}
      >
        Refresh sessions
      </button>
    </section>
  );
}
