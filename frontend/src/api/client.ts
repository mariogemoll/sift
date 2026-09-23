import createClient from "openapi-fetch";

import type { components, paths } from "./schema";

export type Paper = components["schemas"]["PaperOut"];
export type PaperPage = components["schemas"]["PaperPage"];
export type Health = components["schemas"]["HealthResponse"];
export type Session = components["schemas"]["SessionStatus"];

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

export async function fetchPapers(limit = 50, offset = 0): Promise<PaperPage> {
  const { data, error, response } = await api.GET("/papers", {
    params: { query: { limit, offset } },
  });
  if (error) {
    if (response.status === 401) throw new Unauthorized();
    throw new Error("could not load papers");
  }
  return data;
}
