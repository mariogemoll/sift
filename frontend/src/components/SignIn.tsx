import { useState, type FormEvent } from "react";

import { messageOf } from "../api/client";

/**
 * The whole login. One field, because there is one shared passphrase and no
 * accounts; `current-password` so a password manager can keep it.
 */
export function SignIn({
  configured,
  onEnter,
}: {
  configured: boolean;
  onEnter: (passphrase: string) => Promise<void>;
}) {
  const [passphrase, setPassphrase] = useState("");
  const [checking, setChecking] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setChecking(true);
    setError(null);
    try {
      await onEnter(passphrase);
    } catch (thrown: unknown) {
      // On success this form is gone, so only the failure path comes back here.
      setError(messageOf(thrown));
      setPassphrase("");
      setChecking(false);
    }
  };

  return (
    <main className="gate">
      <form
        onSubmit={(event) => {
          void submit(event);
        }}
      >
        <h1>sift</h1>
        <p className="note">
          Rank a pile of documents against weighted criteria.
        </p>

        {configured ? (
          <>
            <label htmlFor="passphrase">Passphrase</label>
            <input
              id="passphrase"
              name="passphrase"
              type="password"
              value={passphrase}
              onChange={(event) => setPassphrase(event.target.value)}
              autoComplete="current-password"
              autoFocus
              disabled={checking}
            />
            <button type="submit" disabled={checking || passphrase.length === 0}>
              {checking ? "Checking…" : "Enter"}
            </button>
          </>
        ) : (
          <p className="note error">
            No passphrase is configured here, so nobody can sign in. Mint one
            with <code>sift passphrase</code> and set{" "}
            <code>SIFT_PASSPHRASE_HASH</code>.
          </p>
        )}

        {error !== null && <p className="note error">{error}</p>}
      </form>
    </main>
  );
}
