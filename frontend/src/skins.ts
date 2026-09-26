type Skin = { image: string; model: "default" | "slim" };
const cache = new Map<
  string,
  { expires: number; skin: Promise<Skin | null> }
>();
// Share the texture between 2D avatars and the 3D preview, including in-flight loads.
// Serialize unique lookups to stay within the server's small skin-fetch pool.
let pending = Promise.resolve();

export function loadSkin(uuid: string): Promise<Skin | null> {
  if (!/^[0-9a-f]{32}$/.test(uuid)) return Promise.resolve(null);
  const cached = cache.get(uuid);
  if (cached && cached.expires > Date.now()) return cached.skin;
  const skin = pending.then(async () => {
    try {
      const response = await fetch(`/api/v1/party/skin/${uuid}`, {
        credentials: "same-origin",
        cache: "no-store",
        signal: AbortSignal.timeout(12000),
      });
      if (!response.ok) return null;
      const result = (await response.json()) as Skin;
      return typeof result.image === "string" &&
        result.image.length <= 90000 &&
        /^data:image\/png;base64,[A-Za-z0-9+/=]+$/.test(result.image) &&
        (result.model === "default" || result.model === "slim")
        ? result
        : null;
    } catch {
      return null;
    }
  });
  const entry = { expires: Infinity, skin };
  pending = skin.then((value) => {
    entry.expires = Date.now() + (value ? 300000 : 30000);
  });
  cache.delete(uuid);
  cache.set(uuid, entry);
  while (cache.size > 128) cache.delete(cache.keys().next().value!);
  return skin;
}
