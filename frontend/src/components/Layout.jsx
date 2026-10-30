import { Navigate, Outlet } from 'react-router-dom';
import { useAuth } from '../context/AuthContext.jsx';
import { LiveProvider, useLive } from '../context/LiveContext.jsx';
import Sidebar from './Sidebar.jsx';
import Toasts from './Toasts.jsx';

function Shell() {
  const { error } = useLive();
  return (
    <div className="app">
      <Sidebar />
      <main>
        {error && (
          <div className="note bad" role="alert">
            {error}
          </div>
        )}
        <Outlet />
      </main>
      <Toasts />
    </div>
  );
}

/** Logged-in area: redirects to /login without a session. */
export default function Layout() {
  const { session } = useAuth();
  if (!session) return <Navigate to="/login" replace />;
  return (
    <LiveProvider>
      <Shell />
    </LiveProvider>
  );
}
