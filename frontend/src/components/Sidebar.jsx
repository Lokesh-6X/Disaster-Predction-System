import { useState } from 'react';
import { NavLink } from 'react-router-dom';
import { useAuth } from '../context/AuthContext.jsx';
import { useLive } from '../context/LiveContext.jsx';
import { fixed } from '../utils/format.js';
import { BellIcon, DashboardIcon, HistoryIcon, KitIcon, Logo, MenuIcon, SignOutIcon } from './Icons.jsx';
import ThemeToggle from './ThemeToggle.jsx';

const LINKS = [
  { to: '/', label: 'Dashboard', icon: DashboardIcon, end: true },
  { to: '/history', label: 'History', icon: HistoryIcon },
  { to: '/alerts', label: 'Alerts', icon: BellIcon, count: true },
  { to: '/kits', label: 'Kits', icon: KitIcon },
];

export default function Sidebar() {
  const { logout } = useAuth();
  const { system, alertCount } = useLive();
  const [open, setOpen] = useState(false);
  const site = system?.site;

  return (
    <nav className={`side${open ? ' open' : ''}`} aria-label="Main">
      <div className="side-top">
        <NavLink to="/" className="brand" onClick={() => setOpen(false)}>
          <Logo />
          <div>
            <b>SkyWatch</b>
            <span className="label">Hazard console</span>
          </div>
        </NavLink>
        <button
          type="button"
          className="menu-btn"
          aria-expanded={open}
          aria-label={open ? 'Close menu' : 'Open menu'}
          onClick={() => setOpen((o) => !o)}
        >
          <MenuIcon />
        </button>
      </div>
      <div className="side-body">
        <div className="navlinks">
          {LINKS.map(({ to, label, icon: Icon, end, count }) => (
            <NavLink key={to} to={to} end={end} onClick={() => setOpen(false)}>
              <Icon />
              {label}
              {count && alertCount > 0 && (
                <span className="count" title="Alerts in the last 24 hours">
                  {alertCount}
                </span>
              )}
            </NavLink>
          ))}
        </div>
        <div className="side-foot">
          <div className="sitebox">
            <span className="label">Site</span>
            <span style={{ fontWeight: 600, fontSize: 15 }}>{site?.name ?? '—'}</span>
            {site && (
              <span className="mono small muted">
                {fixed(site.latitude, 2)}°N, {fixed(site.longitude, 2)}°E
              </span>
            )}
            <span className="mono small muted">from config/site.yaml</span>
          </div>
          <ThemeToggle />
          <button type="button" className="side-action" onClick={() => logout()}>
            <SignOutIcon />
            Sign out
          </button>
        </div>
      </div>
    </nav>
  );
}
