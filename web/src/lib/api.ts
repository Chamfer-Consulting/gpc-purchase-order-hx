import { supabase } from "./supabase";

const BASE = import.meta.env.VITE_API_BASE ?? "";

/** A FastAPI 422 validation entry. */
export interface FieldError {
  loc: (string | number)[];
  msg: string;
  type?: string;
}

export class ApiError extends Error {
  /** stable machine code for a typed backend problem (errors.py), e.g. "stale_write" */
  code?: string;
  /** FastAPI request-validation entries (422 with a list body) */
  fields?: FieldError[];
  /** extra payload from a typed problem (current_version, allowed, status, ...) */
  data?: Record<string, unknown>;

  constructor(
    public status: number,
    message: string,
    opts?: { code?: string; fields?: FieldError[]; data?: Record<string, unknown> },
  ) {
    super(message);
    this.code = opts?.code;
    this.fields = opts?.fields;
    this.data = opts?.data;
  }
}

/** Turn a parsed error body's `detail` into ApiError constructor options + message. */
function parseDetail(detail: unknown, fallback: string): {
  message: string;
  opts: { code?: string; fields?: FieldError[]; data?: Record<string, unknown> };
} {
  if (typeof detail === "string") return { message: detail, opts: {} };
  if (Array.isArray(detail)) {
    const fields = detail as FieldError[];
    return { message: fields[0]?.msg ?? "Validation failed", opts: { fields } };
  }
  if (detail && typeof detail === "object") {
    const d = detail as Record<string, unknown>;
    const { code, message, ...rest } = d;
    return {
      message: typeof message === "string" ? message : fallback,
      opts: { code: typeof code === "string" ? code : undefined, data: rest },
    };
  }
  return { message: fallback, opts: {} };
}

/** GET a JSON endpoint on the FastAPI backend with the current Supabase access token. */
export async function apiGet<T>(path: string, params?: Record<string, unknown>): Promise<T> {
  return request<T>("GET", path, params);
}

export async function apiSend<T>(
  method: "POST" | "PUT" | "DELETE",
  path: string,
  body?: unknown,
): Promise<T> {
  return request<T>(method, path, undefined, body);
}

/**
 * Best-effort: tell the backend a sign-in / sign-out happened so it lands in the
 * audit trail. Never throws — the auth flow must not hinge on it. The backend is
 * idempotent per browser session, so calling it more than once is harmless.
 */
export async function recordActivity(event: "login" | "logout"): Promise<void> {
  try {
    await apiSend("POST", "/api/activity", { event });
  } catch {
    /* the audit ping is not critical */
  }
}

/**
 * Fetch a binary endpoint (e.g. a stored PDF) with the Supabase token and return
 * an object URL for it. Caller is responsible for URL.revokeObjectURL when done.
 */
export async function fetchBlobUrl(path: string): Promise<string> {
  const { data } = await supabase.auth.getSession();
  const token = data.session?.access_token;
  const url = new URL(path, BASE || window.location.origin);
  const res = await fetch(url.toString(), {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!res.ok) {
    let detail: unknown = res.statusText;
    try {
      detail = (await res.json())?.detail ?? detail;
    } catch {
      /* non-JSON error body */
    }
    const { message, opts } = parseDetail(detail, res.statusText);
    throw new ApiError(res.status, message, opts);
  }
  return URL.createObjectURL(await res.blob());
}

async function request<T>(
  method: string,
  path: string,
  params?: Record<string, unknown>,
  body?: unknown,
): Promise<T> {
  const { data } = await supabase.auth.getSession();
  const token = data.session?.access_token;

  const url = new URL(path, BASE || window.location.origin);
  if (params) {
    for (const [k, v] of Object.entries(params)) {
      if (v === undefined || v === null || v === "") continue;
      if (Array.isArray(v)) {
        // repeated key (?k=a&k=b) — so a value containing a comma survives
        for (const item of v) {
          if (item !== undefined && item !== null && item !== "") {
            url.searchParams.append(k, String(item));
          }
        }
      } else {
        url.searchParams.set(k, String(v));
      }
    }
  }

  const res = await fetch(url.toString(), {
    method,
    headers: {
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
    },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });

  if (!res.ok) {
    let detail: unknown = res.statusText;
    try {
      detail = (await res.json())?.detail ?? detail;
    } catch {
      /* non-JSON error body */
    }
    const { message, opts } = parseDetail(detail, res.statusText);
    throw new ApiError(res.status, message, opts);
  }
  return res.json() as Promise<T>;
}
