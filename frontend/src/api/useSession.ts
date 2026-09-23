import { useCallback, useEffect, useState } from "react";

import {
  fetchSession,
  messageOf,
  signIn,
  signOut,
  type Session,
} from "./client";

export type SessionView =
  | { status: "checking" }
  | { status: "unreachable"; message: string }
  | { status: "out"; configured: boolean }
  | { status: "in" };

export type SessionHandle = {
  view: SessionView;
  enter: (passphrase: string) => Promise<void>;
  leave: () => Promise<void>;
  ended: () => void;
};

const viewOf = (session: Session): SessionView =>
  session.authenticated
    ? { status: "in" }
    : { status: "out", configured: session.configured };

/**
 * Whether we hold a session, and the three things that change it.
 *
 * `enter` rejects when the passphrase is wrong, so the form reports the reason
 * beside the field it belongs to instead of this hook carrying an error state.
 */
export function useSession(): SessionHandle {
  const [view, setView] = useState<SessionView>({ status: "checking" });

  useEffect(() => {
    let live = true;
    fetchSession().then(
      (session) => {
        if (live) setView(viewOf(session));
      },
      (error: unknown) => {
        if (live) setView({ status: "unreachable", message: messageOf(error) });
      },
    );
    return () => {
      live = false;
    };
  }, []);

  const enter = useCallback(async (passphrase: string) => {
    setView(viewOf(await signIn(passphrase)));
  }, []);

  const leave = useCallback(async () => {
    await signOut();
    setView({ status: "out", configured: true });
  }, []);

  const ended = useCallback(() => {
    setView({ status: "out", configured: true });
  }, []);

  return { view, enter, leave, ended };
}
