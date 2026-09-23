import createClient from "openapi-fetch";

import type { components, paths } from "./schema";

export type Paper = components["schemas"]["PaperOut"];
export type Verdict = components["schemas"]["VerdictOut"];
export type Assessed = components["schemas"]["AssessedOut"];
export type PaperPage = components["schemas"]["PaperPage"];
export type Profile = components["schemas"]["ProfileOut"];
/** The stage an item waits for, or how it ended. The schema keys progress by plain string. */
export type ItemState = "screen" | "fetch" | "judge" | "done" | "dead";
export type Health = components["schemas"]["HealthResponse"];
export type Session = components["schemas"]["SessionStatus"];
export type Batch = components["schemas"]["BatchOut"];

// Relative, so the dev server's proxy and the deployed origin behave alike.
// Same-origin means fetch sends the session cookie without being asked to.
export const api = createClient<paths>({ baseUrl: "/api" });

export const messageOf = (error: unknown): string =>
  error instanceof Error ? error.message : String(error);

/** The session is gone: the cookie expired, or the passphrase was rotated. */
export class Unauthorized extends Error {
  constructor() {
    super("your session has ended");
    this.name = "Unauthorized";
  }
}

export async function fetchHealth(): Promise<Health> {
  const { data, error } = await api.GET("/health");
  if (error) throw new Error("health check failed");
  return data;
}

export async function fetchSession(): Promise<Session> {
  const { data, error } = await api.GET("/auth/session");
  if (error) throw new Error("could not reach the api");
  return data;
}

export async function signIn(passphrase: string): Promise<Session> {
  const { data, error, response } = await api.POST("/auth/session", {
    body: { passphrase },
  });
  if (error) {
    if (response.status === 401) throw new Error("That is not the passphrase.");
    if (response.status === 503) {
      throw new Error("This deployment has no passphrase configured.");
    }
    throw new Error("Signing in failed.");
  }
  return data;
}

export async function signOut(): Promise<void> {
  const { error } = await api.DELETE("/auth/session");
  if (error) throw new Error("could not sign out");
}

export type Order = "rank" | "newest";

export interface PaperQuery {
  limit: number;
  /** Published within this many days; null for every paper. */
  days: number | null;
  order: Order;
}

export async function fetchPapers({ limit, days, order }: PaperQuery): Promise<PaperPage> {
  const { data, error, response } = await api.GET("/papers", {
    params: { query: { limit, order, ...(days === null ? {} : { days }) } },
  });
  if (error) {
    if (response.status === 401) throw new Unauthorized();
    throw new Error("could not load papers");
  }
  return data;
}

export async function fetchProfile(): Promise<Profile> {
  // The route declares no error body, so only the missing data tells of a failure.
  const { data, response } = await api.GET("/profile");
  if (data === undefined) {
    if (response.status === 401) throw new Unauthorized();
    throw new Error("could not load the wishlist");
  }
  return data;
}

/** Queue one batch per category the wishlist names: each fetches its latest announcement. */
export async function submitBatches(): Promise<Batch[]> {
  // The route declares no error body, so only the missing data tells of a failure.
  const { data, response } = await api.POST("/batches");
  if (data === undefined) {
    if (response.status === 401) throw new Unauthorized();
    throw new Error(`queueing failed (${response.status})`);
  }
  return data;
}

export async function fetchBatches(limit = 10): Promise<Batch[]> {
  const { data, error, response } = await api.GET("/batches", {
    params: { query: { limit } },
  });
  if (error !== undefined || data === undefined) {
    if (response.status === 401) throw new Unauthorized();
    throw new Error("could not load batches");
  }
  return data;
}
