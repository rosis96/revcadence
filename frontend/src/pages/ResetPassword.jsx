// Public password-reset page (rendered outside the auth gate). Opened from a
// one-time reset link (#/reset/{token}).
import { useState } from "react";
import { useParams } from "react-router-dom";

function Wave({ size = 120 }) {
  return (
    <svg viewBox="80 20 560 235" width={size} height={size * 0.42} aria-hidden="true" style={{ color: "var(--accent, #635BFF)" }}>
      <path d="M104 235 L121 235 C134 235 134 204 147 204 C160 204 160 235 173 235 C186 235 186 197 199 197 C212 197 212 235 225 235 C238 235 238 177 251 177 C264 177 264 235 277 235 C290 235 290 154 303 154 C316 154 316 235 329 235 C342 235 342 129 355 129 C368 129 368 235 381 235 C394 235 394 101 407 101 C420 101 420 235 433 235 C446 235 446 72 459 72 C472 72 472 235 485 235 C498 235 498 42 511 42 C524 42 524 235 537 235 L553 235"
        fill="none" stroke="currentColor" strokeWidth="20" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export default function ResetPassword() {
  const { token } = useParams();
  const [p1, setP1] = useState("");
  const [p2, setP2] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setError("");
    if (p1.length < 12) { setError("Password must be at least 12 characters."); return; }
    if (p1 !== p2) { setError("Passwords don't match."); return; }
    setBusy(true);
    try {
      const res = await fetch("/api/auth/reset", { method: "POST",
        headers: { "Content-Type": "application/json" }, body: JSON.stringify({ token, password: p1 }) });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Could not reset password");
      setDone(true);
    } catch (err) { setError(err.message); }
    setBusy(false);
  };

  return (
    <div className="login-wrap">
      <div className="login-card">
        <div style={{ display: "flex", flexDirection: "column", alignItems: "center", marginBottom: 18 }}>
          <Wave />
          <h1 style={{ marginTop: 6 }}>Rev<span>Cadence</span></h1>
          <p style={{ marginTop: 2 }}>Set a new password</p>
        </div>
        {error && <div className="error-box" style={{ marginBottom: 12 }}>{error}</div>}
        {done ? (
          <div style={{ textAlign: "center" }}>
            <div style={{ fontSize: 34, color: "var(--ok,#12b76a)" }}>✓</div>
            <p style={{ margin: "8px 0" }}>Your password has been updated.</p>
            <a className="btn" style={{ display: "inline-block", width: "100%" }} href="/#/">Go to sign in</a>
          </div>
        ) : (
          <form onSubmit={submit}>
            <label>New password</label>
            <input type="password" value={p1} onChange={(e) => setP1(e.target.value)} autoFocus required placeholder="at least 12 characters" />
            <label>Confirm password</label>
            <input type="password" value={p2} onChange={(e) => setP2(e.target.value)} required />
            <button className="btn" disabled={busy} style={{ width: "100%", marginTop: 4 }}>{busy ? "Saving…" : "Update password"}</button>
          </form>
        )}
      </div>
    </div>
  );
}
