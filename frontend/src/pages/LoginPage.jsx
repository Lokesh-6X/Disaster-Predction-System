import { useEffect, useState } from 'react';
import { Navigate } from 'react-router-dom';
import { api } from '../api/client.js';
import { Logo } from '../components/Icons.jsx';
import ThemeToggle from '../components/ThemeToggle.jsx';
import { useAuth } from '../context/AuthContext.jsx';

function Illustration() {
  return (
    <svg viewBox="0 0 520 220" style={{ width: '100%', maxWidth: 520, height: 'auto' }} aria-hidden="true">
      <circle cx="110" cy="110" r="96" fill="none" stroke="var(--line)" />
      <circle cx="110" cy="110" r="64" fill="none" stroke="var(--line)" />
      <circle cx="110" cy="110" r="32" fill="none" stroke="var(--line)" />
      <path d="M110 14 A96 96 0 0 1 200 76" fill="none" stroke="var(--orange)" strokeWidth="6" strokeLinecap="round" />
      <path d="M174 110 A64 64 0 0 1 150 160" fill="none" stroke="var(--yellow)" strokeWidth="6" strokeLinecap="round" />
      <path d="M110 78 A32 32 0 0 1 140 98" fill="none" stroke="var(--green)" strokeWidth="6" strokeLinecap="round" />
      <circle cx="110" cy="110" r="5" fill="var(--accent)" />
      <polyline
        points="250,150 280,140 310,146 340,120 370,126 400,96 430,104 460,72 490,80 520,52"
        fill="none"
        stroke="var(--accent)"
        strokeWidth="2.5"
        strokeLinejoin="round"
      />
      <line x1="250" y1="180" x2="520" y2="180" stroke="var(--line)" />
    </svg>
  );
}

export default function LoginPage() {
  const { session, login, notice } = useAuth();
  const [siteName, setSiteName] = useState('your site');
  const [version, setVersion] = useState('');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api
      .get('/api/health')
      .then((health) => {
        setSiteName(health.site);
        setVersion(health.version);
      })
      .catch(() => {});
  }, []);

  if (session) return <Navigate to="/" replace />;

  const submit = async (event) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(username.trim(), password);
    } catch (err) {
      setError(err.message);
      setBusy(false);
    }
  };

  return (
    <div className="login">
      <section className="left" aria-label="About">
        <div className="brand">
          <Logo size={38} />
          <b style={{ fontSize: 20 }}>SkyWatch</b>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 28 }}>
          <Illustration />
          <h1 style={{ fontSize: 48, lineHeight: 1.05, letterSpacing: '-.02em', maxWidth: 520 }}>
            Three hours of warning, from one sensor kit.
          </h1>
          <p style={{ margin: 0, fontSize: 17, lineHeight: 1.6, color: 'var(--text2)', maxWidth: 480 }}>
            Live readings, heat-wave and high-wind risk for {siteName}, refreshed every hour.
          </p>
        </div>
        <span className="mono small muted">Admin access only{version ? ` · v${version}` : ''}</span>
      </section>
      <section className="right" aria-label="Sign in">
        <div className="theme-corner">
          <ThemeToggle className="btn-ghost" />
        </div>
        <form className="signin" onSubmit={submit}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            <h2 style={{ fontSize: 28 }}>Sign in</h2>
            <p style={{ margin: 0, color: 'var(--text2)', fontSize: 15 }}>Use your admin account.</p>
          </div>
          {(error || notice) && (
            <p className="form-error" role="alert">
              {error || notice}
            </p>
          )}
          <div className="field">
            <label htmlFor="username">Username or email</label>
            <input
              id="username"
              autoComplete="username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              required
              autoFocus
            />
          </div>
          <div className="field">
            <label htmlFor="password">Password</label>
            <div className="pw">
              <input
                id="password"
                type={showPassword ? 'text' : 'password'}
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
              />
              <button type="button" onClick={() => setShowPassword((s) => !s)} aria-pressed={showPassword}>
                {showPassword ? 'Hide' : 'Show'}
              </button>
            </div>
          </div>
          <button className="btn" type="submit" disabled={busy}>
            {busy ? 'Signing in…' : 'Sign in'}
          </button>
          <p style={{ margin: 0, fontSize: 13, color: 'var(--muted)', lineHeight: 1.5 }}>
            Forgot your password? The admin account comes from the server's .env file.
          </p>
        </form>
      </section>
    </div>
  );
}
