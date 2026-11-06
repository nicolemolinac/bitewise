/**
 * Accept only canonical HTTPS REWE product detail links.
 * Keep this allowlist in sync with backend/app/rewe/scraper.py.
 */
export function isCanonicalReweProductUrl(value) {
  try {
    const url = new URL(value || "");
    return (
      url.protocol === "https:" &&
      (url.hostname.toLowerCase() === "www.rewe.de" || url.hostname.toLowerCase() === "rewe.de") &&
      url.pathname.startsWith("/shop/p/")
    );
  } catch {
    return false;
  }
}
