const RETURN_PATH_KEY = "eeze-pair-return";

/** Only an app path on this origin may be restored after pairing. */
export function safeReturnPath(candidate: string | null): string {
  if (
    !candidate ||
    !candidate.startsWith("/") ||
    candidate.startsWith("//") ||
    candidate.includes("\\") ||
    Array.from(candidate).some((char) => char.charCodeAt(0) < 32 || char.charCodeAt(0) === 127)
  ) {
    return "/";
  }
  const path = new URL(candidate, "http://localhost");
  if (
    path.origin !== "http://localhost" ||
    ["/pair", "/api", "/artifacts"].some(
      (prefix) => path.pathname === prefix || path.pathname.startsWith(`${prefix}/`),
    )
  ) {
    return "/";
  }
  return candidate;
}

let redirecting = false;

/** A 401 means this browser needs a local operator pairing cookie. */
export function redirectToPair(): void {
  if (
    import.meta.env["VITE_DEMO_MODE"] === "true" ||
    redirecting ||
    location.pathname === "/pair"
  ) {
    return;
  }
  redirecting = true;
  try {
    sessionStorage.setItem(
      RETURN_PATH_KEY,
      safeReturnPath(`${location.pathname}${location.search}${location.hash}`),
    );
  } catch {
    // Storage can be blocked; the pairing page then returns home.
  }
  location.assign("/pair");
}

export function takeReturnPath(): string {
  let path: string | null = null;
  try {
    path = sessionStorage.getItem(RETURN_PATH_KEY);
    sessionStorage.removeItem(RETURN_PATH_KEY);
  } catch {
    // No storage: return to the local home page.
  }
  return safeReturnPath(path);
}
