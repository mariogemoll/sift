import createClient from "openapi-fetch";

import type { components, paths } from "./schema";

export type Paper = components["schemas"]["PaperOut"];
export type PaperPage = components["schemas"]["PaperPage"];
export type Health = components["schemas"]["HealthResponse"];

// Relative, so the dev server's proxy and the deployed origin behave alike.
export const api = createClient<paths>({ baseUrl: "/api" });

export async function fetchHealth(): Promise<Health> {
  const { data, error } = await api.GET("/health");
  if (error) throw new Error("health check failed");
  return data;
}

export async function fetchPapers(limit = 50, offset = 0): Promise<PaperPage> {
  const { data, error } = await api.GET("/papers", {
    params: { query: { limit, offset } },
  });
  if (error) throw new Error("could not load papers");
  return data;
}
