export const TOOLS = [
  { id: 'codex', label: 'ChatGPT', long: 'ChatGPT (Codex)', color: '#22D3EE' },
  { id: 'claude_code', label: 'Claude', long: 'Claude', color: '#F59E0B' },
  { id: 'antigravity', label: 'Antigravity', long: 'Antigravity', color: '#A78BFA' },
  { id: 'gemini_cli', label: 'Gemini', long: 'Gemini', color: '#60A5FA' },
] as const;

export const toolOf = (id: string) => TOOLS.find((t) => t.id === id);
export const colorOf = (id: string) => toolOf(id)?.color || '#8B8FA3';

export const EXAMPLE_ROADMAP = [
  { title: 'Plan the login page', owner: 'chatgpt', description: 'List only the major info: the fields, the buttons, the checks and the error message. Keep it to a few lines.', done_when: 'the plan is saved in the task note' },
  { title: 'Build login.html', owner: 'claude', description: 'A simple login.html in the project folder: a form with email and password fields, a Sign in button and a Forgot password link. Plain HTML only, no styling. Link style.css in the head. In the task note, list the ids and classes you used so the CSS can target them.', done_when: 'login.html exists and the ids and classes are in the task note', depends_on: [1] },
  { title: 'Write style.css', owner: 'antigravity', description: 'Create style.css in the project folder that styles login.html (a centred card, clean fonts, a clear button) using the ids and classes from the task note.', done_when: 'style.css exists and login.html looks good in a browser', depends_on: [2] },
];

export function ago(iso?: string | null): string {
  if (!iso) return 'never';
  const s = Math.max(0, Math.floor((Date.now() - new Date(iso).getTime()) / 1000));
  if (s < 10) return 'just now';
  if (s < 90) return `${s}s ago`;
  if (s < 5400) return `${Math.round(s / 60)}m ago`;
  if (s < 86400) return `${Math.round(s / 3600)}h ago`;
  return `${Math.round(s / 86400)}d ago`;
}
