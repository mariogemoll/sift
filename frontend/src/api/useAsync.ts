import { useEffect, useState, type DependencyList } from "react";

import { messageOf } from "./client";

export type Async<T> =
  | { status: "loading" }
  | { status: "ready"; value: T }
  | { status: "failed"; message: string; error: unknown };

/**
 * Run `load` on mount, and again whenever `deps` change, and report which of the
 * three states we are in.
 *
 * A rerun keeps showing the previous value until the new one arrives, so a
 * reload does not flash the loading state. `load` is read when `deps` change,
 * not on every render; a result arriving after unmount or after a newer run
 * started is dropped. The failure keeps the thrown value as well as its message,
 * so a caller can tell one kind apart from another.
 */
export function useAsync<T>(
  load: () => Promise<T>,
  deps: DependencyList = [],
): Async<T> {
  const [state, setState] = useState<Async<T>>({ status: "loading" });

  useEffect(() => {
    let live = true;
    load().then(
      (value) => {
        if (live) setState({ status: "ready", value });
      },
      (error: unknown) => {
        if (live) setState({ status: "failed", message: messageOf(error), error });
      },
    );
    return () => {
      live = false;
    };
  }, deps);

  return state;
}
