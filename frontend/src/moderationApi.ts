/** Same-origin moderation API calls; errors carry the server's explanation. */
export async function request<T>(path: string, body?: object): Promise<T> {
  const response = await fetch(`/api/v1/moderation/${path}`, {
    method: body ? "POST" : "GET",
    credentials: "same-origin",
    cache: "no-store",
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify({ version: 1, ...body }) : undefined,
    signal: AbortSignal.timeout(15000),
  });
  if (!response.ok) {
    const value = (await response.json()) as { detail?: unknown };
    throw new Error(
      typeof value.detail === "string"
        ? value.detail
        : "Check the entered values and try again.",
    );
  }
  return response.json() as Promise<T>;
}
