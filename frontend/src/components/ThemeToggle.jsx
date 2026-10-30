import { useTheme } from '../context/ThemeContext.jsx';
import { ThemeIcon } from './Icons.jsx';

const LABELS = { system: 'Theme: system', light: 'Theme: light', dark: 'Theme: dark' };

export default function ThemeToggle({ className = 'side-action' }) {
  const { mode, theme, cycle } = useTheme();
  return (
    <button type="button" className={className} onClick={cycle} title="Switch theme (system → light → dark)">
      <ThemeIcon theme={theme} />
      {LABELS[mode]}
    </button>
  );
}
