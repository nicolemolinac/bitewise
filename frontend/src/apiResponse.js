/**
 * Parse FastAPI responses and expose the human-readable detail instead of raw JSON.
 * Handles validation arrays and plain-text proxy/server failures too.
 */
export async function parseApiResponse(response) {
  const raw = await response.text();
  let payload = null;
  if (raw) {
    try {
      payload = JSON.parse(raw);
    } catch {
      payload = raw;
    }
  }

  if (!response.ok) {
    let message = "";
    if (payload && typeof payload === "object" && !Array.isArray(payload)) {
      if (typeof payload.detail === "string") {
        message = payload.detail;
      } else if (Array.isArray(payload.detail)) {
        message = payload.detail.map((item) => {
          const location = Array.isArray(item?.loc) ? item.loc.join(".") : "";
          const reason = item?.msg || "Invalid value";
          return location ? `${location}: ${reason}` : reason;
        }).join("; ");
      } else if (typeof payload.message === "string") {
        message = payload.message;
      }
    }
    if (!message) message = typeof payload === "string" ? payload : `HTTP ${response.status}`;
    throw new Error(message);
  }

  if (typeof payload === "string") {
    throw new Error("Bitewise API returned an invalid JSON response.");
  }
  return payload;
}
