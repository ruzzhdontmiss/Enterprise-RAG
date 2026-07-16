const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

/**
 * Resolves paths against the NEXT_PUBLIC_API_URL environment variable,
 * enforcing a protocol scheme to prevent relative browser routing errors.
 * 
 * @param path The endpoint path (e.g. "/auth/login", "documents")
 * @returns The fully qualified absolute URL string
 */
export function getApiUrl(path: string): string {
  // Trim leading slash from path to prevent double slash in join
  const cleanPath = path.startsWith("/") ? path.slice(1) : path;
  
  // Clean and parse base url
  let base = API_URL.trim();
  
  // Enforce HTTP/HTTPS scheme prefix
  if (!base.startsWith("http://") && !base.startsWith("https://")) {
    base = `https://${base}`;
  }
  
  // Remove trailing slash from base if present
  if (base.endsWith("/")) {
    base = base.slice(0, -1);
  }
  
  return `${base}/${cleanPath}`;
}
