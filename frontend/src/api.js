// Single source of truth for the backend base URL.
//
// In development: VITE_API_BASE_URL is unset and we use relative URLs, which
// the Vite dev server proxies to http://127.0.0.1:8000 (see vite.config.js).
//
// In production: set VITE_API_BASE_URL in the Vercel project to the
// Railway backend URL (no trailing slash), and the bundled JS will call
// that origin directly. The backend's CORS allow_origins must include
// the Vercel domain.

const API_BASE = (import.meta.env.VITE_API_BASE_URL || "").replace(/\/+$/, "");

export function apiUrl(path) {
  return `${API_BASE}${path}`;
}
