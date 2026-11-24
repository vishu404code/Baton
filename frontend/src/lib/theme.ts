export type Theme = 'light' | 'dark';

export function getTheme(): Theme {
  try {
    const t = localStorage.getItem('baton_theme');
    if (t === 'light' || t === 'dark') return t;
  } catch {
    /* ignore */
  }
  return 'dark';
}

export function applyTheme(t: Theme) {
  document.documentElement.classList.toggle('light', t === 'light');
  try {
    localStorage.setItem('baton_theme', t);
  } catch {
    /* ignore */
  }
}
