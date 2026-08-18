// The forced first-login password change.
//
// Shown instead of the app — not on top of it — because until this is done the
// session cannot do anything else: every business route refuses an account still
// holding the temporary password from its invite. Rendering the shell behind a
// modal would show a workspace whose every request is about to 403.
//
// Deliberately the same card as the sign-in screen. This is still the front door,
// one step further in, and a different visual language here would read as a
// phishing page to the exact person we are asking to type a password.
import { useEffect, useRef, useState } from "react";
import { Eye, EyeOff, LogOut } from "lucide-react";
import { motion } from "framer-motion";
import { api } from "../api";
import { useAuth } from "../auth";

const MIN = 6;

export default function ChangePassword() {
  const { me, logout, reloadMe } = useAuth();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [show, setShow] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const firstRef = useRef(null);
  useEffect(() => { firstRef.current?.focus(); }, []);

  const tooShort = next.length > 0 && next.length < MIN;
  const mismatch = confirm.length > 0 && confirm !== next;
  const ready = current && next.length >= MIN && confirm === next && !busy;

  const submit = async (e) => {
    e.preventDefault();
    if (!ready) return;
    setBusy(true); setError("");
    try {
      await api("/api/auth/change-password", {
        method: "POST", body: { current_password: current, new_password: next },
      });
      await reloadMe();          // clears the flag and drops us into the workspace
    } catch (err) {
      setError(err.message);
      setBusy(false);
    }
  };

  return (
    <div className="login-wrap">
      <motion.div className="login-card" initial={{ opacity: 0, y: 20, scale: 0.985 }}
        animate={{ opacity: 1, y: 0, scale: 1 }} transition={{ duration: 0.42, ease: [0.16, 1, 0.3, 1] }}>
        <div style={{ display: "flex", flexDirection: "column", alignItems: "center", marginBottom: 18 }}>
          <h1 style={{ marginTop: 6 }}>Choose your password</h1>
          <p style={{ marginTop: 2, textAlign: "center" }}>
            You signed in with a temporary password. Pick your own to finish setting up
            {me?.workspaces?.[0]?.name ? ` ${me.workspaces[0].name}` : " your workspace"}.
          </p>
        </div>

        {error && <div className="error-box" style={{ marginBottom: 12 }}>{error}</div>}

        <form onSubmit={submit}>
          <label>Temporary password</label>
          <input ref={firstRef} type={show ? "text" : "password"} value={current}
            onChange={(e) => setCurrent(e.target.value)} autoComplete="current-password" required />

          <label>New password</label>
          <div className="password-control">
            <input type={show ? "text" : "password"} value={next} onChange={(e) => setNext(e.target.value)}
              autoComplete="new-password" required minLength={MIN} />
            <button type="button" className="password-toggle" onClick={() => setShow((v) => !v)}
              aria-label={show ? "Hide passwords" : "Show passwords"}>
              {show ? <EyeOff size={19} /> : <Eye size={19} />}
            </button>
          </div>
          <div className={`pw-hint ${tooShort ? "bad" : ""}`}>
            {tooShort ? `${MIN - next.length} more characters needed` : `At least ${MIN} characters.`}
          </div>

          <label>Confirm new password</label>
          <input type={show ? "text" : "password"} value={confirm}
            onChange={(e) => setConfirm(e.target.value)} autoComplete="new-password" required />
          {mismatch && <div className="pw-hint bad">Both fields must match.</div>}

          <motion.button className="btn" disabled={!ready} whileHover={ready ? { y: -1 } : undefined}
            whileTap={ready ? { scale: 0.99 } : undefined}>
            {busy ? "Saving…" : "Save and continue"}
          </motion.button>
        </form>

        <div className="forgot-row" style={{ justifyContent: "center", marginTop: 14 }}>
          <button type="button" className="linkbtn" onClick={logout}>
            <LogOut size={14} style={{ verticalAlign: "-2px", marginRight: 5 }} />
            Sign in as someone else
          </button>
        </div>
      </motion.div>
    </div>
  );
}
