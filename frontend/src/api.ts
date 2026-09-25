export type Health = {
  status: "ok";
  service: "mithril-web";
  api_version: 1;
};

export async function getHealth(signal: AbortSignal): Promise<Health> {
  const response = await fetch("/api/v1/health", { signal, cache: "no-store" });
  if (!response.ok) throw new Error("Service unavailable");
  const value: unknown = await response.json();
  if (
    typeof value !== "object" ||
    value === null ||
    !("status" in value) ||
    value.status !== "ok" ||
    !("service" in value) ||
    value.service !== "mithril-web" ||
    !("api_version" in value) ||
    value.api_version !== 1
  ) {
    throw new Error("Unsupported service response");
  }
  return { status: "ok", service: "mithril-web", api_version: 1 };
}
