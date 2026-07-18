import { useState } from "react";
import { useAuth } from "../auth";

// The RevCadence wave mark (same as the sidebar logo).
function Wave({ size = 132 }) {
  return (
    <svg viewBox="80 20 560 235" width={size} height={size * 0.42} aria-hidden="true" style={{ color: "var(--accent, #635BFF)" }}>
      <path d="M104 235 L121 235 C134 235 134 204 147 204 C160 204 160 235 173 235 C186 235 186 197 199 197 C212 197 212 235 225 235 C238 235 238 177 251 177 C264 177 264 235 277 235 C290 235 290 154 303 154 C316 154 316 235 329 235 C342 235 342 129 355 129 C368 129 368 235 381 235 C394 235 394 101 407 101 C420 101 420 235 433 235 C446 235 446 72 459 72 C472 72 472 235 485 235 C498 235 498 42 511 42 C524 42 524 235 537 235 L553 235"
        fill="none" stroke="currentColor" strokeWidth="20" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export default function Login() {
  const { login } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [forgot, setForgot] = useState(false);
  const [sent, setSent] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true); setError("");
    try { await login(email, password); }
    catch (err) { setError(err.message); }
    setBusy(false);
  };

  const doForgot = async (e) => {
    e.preventDefault();
    setBusy(true); setError("");
    try {
      const res = await fetch("/api/auth/forgot", { method: "POST",
        headers: { "Content-Type": "application/json" }, body: JSON.stringify({ email }) });
      await res.json();
      setSent(true);
    } catch { setSent(true); }   // generic — never reveal whether the account exists
    setBusy(false);
  };

  return (
    <div className="login-wrap">
      <div className="login-card">
        <div style={{ display: "flex", flexDirection: "column", alignItems: "center", marginBottom: 18 }}>
          <Wave />
          <h1 style={{ marginTop: 6 }}>Rev<span>Cadence</span></h1>
          <p style={{ marginTop: 2 }}>Your revenue operating system</p>
        </div>

        {error && <div className="error-box" style={{ marginBottom: 12 }}>{error}</div>}

        {!forgot ? (
          <form onSubmit={submit}>
            <label>Email</label>
            <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoFocus required />
            <label>Password</label>
            <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required />
            <button className="btn" disabled={busy} style={{ width: "100%", marginTop: 4 }}>{busy ? "Signing in…" : "Sign in"}</button>
            <div style={{ textAlign: "center", marginTop: 12 }}>
              <button type="button" className="linkbtn" onClick={() => { setForgot(true); setError(""); }}>Forgot password?</button>
            </div>
          </form>
        ) : sent ? (
          <div style={{ textAlign: "center" }}>
            <div style={{ fontSize: 34, color: "var(--ok,#12b76a)" }}>✓</div>
            <p style={{ margin: "8px 0" }}>If <b>{email}</b> has an account, a reset link has been created.
              Check your email, or ask your workspace owner to send it to you.</p>
            <button className="btn" style={{ width: "100%" }} onClick={() => { setForgot(false); setSent(false); }}>Back to sign in</button>
          </div>
        ) : (
          <form onSubmit={doForgot}>
            <p style={{ fontSize: 13, color: "var(--muted)", marginTop: 0 }}>Enter your email and we'll create a secure reset link.</p>
            <label>Email</label>
            <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoFocus required />
            <button className="btn" disabled={busy} style={{ width: "100%", marginTop: 4 }}>{busy ? "Sending…" : "Send reset link"}</button>
            <div style={{ textAlign: "center", marginTop: 12 }}>
              <button type="button" className="linkbtn" onClick={() => { setForgot(false); setError(""); }}>Back to sign in</button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}
