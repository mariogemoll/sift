import { useEffect, useState } from "react";

export type Async<T> =
  | { status: "loading" }
  | { status: "ready"; value: T }
  | { status: "failed"; message: string };

const messageOf = (error: unknown): string =>
  error instanceof Error ? error.message : String(error);

/**
 * Run `load` once on mount and report which of the three states we are in.
 *
 * `load` is read on the first render only; a result arriving after unmount is
 * dropped rather than written to a gone component.
 */
export function useAsync<T>(load: () => Promise<T>): Async<T> {
  const [state, setState] = useState<Async<T>>({ status: "loading" });

  useEffect(() => {
    let live = true;
    load().then(
      (value) => {
        if (live) setState({ status: "ready", value });
      },
      (error: unknown) => {
        if (live) setState({ status: "failed", message: messageOf(error) });
      },
    );
    return () => {
      live = false;
    };
  }, []);

  return state;
}
