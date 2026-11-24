export const TOOLS = [
  { id: 'codex', label: 'ChatGPT', long: 'ChatGPT (Codex)', color: '#22D3EE' },
  { id: 'claude_code', label: 'Claude', long: 'Claude', color: '#F59E0B' },
  { id: 'antigravity', label: 'Antigravity', long: 'Antigravity', color: '#A78BFA' },
  { id: 'gemini_cli', label: 'Gemini', long: 'Gemini', color: '#60A5FA' },
] as const;

export const toolOf = (id: string) => TOOLS.find((t) => t.id === id);
export const colorOf = (id: string) => toolOf(id)?.color || '#8B8FA3';

export const EXAMPLE_ROADMAP = [
  { title: 'Research what visitors want from the app', owner: 'chatgpt', description: 'Summarise who the users are, the 5 must-have features and 3 competitors.', done_when: 'research notes saved in Baton', area: '' },
  { title: 'Build the backend API', owner: 'claude', description: 'Endpoints for articles, places and itineraries, with a database and tests.', done_when: 'tests pass and the endpoints are listed in the task note', depends_on: [1], area: 'backend/' },
  { title: 'Build the frontend screens', owner: 'antigravity', description: 'Home, article, map and itinerary screens that call the API.', done_when: 'screens work against the API', depends_on: [2], area: 'frontend/' },
  { title: 'Review everything and list fixes', owner: 'gemini', description: 'Check that frontend and backend agree and note any bugs.', done_when: 'review notes saved', depends_on: [2, 3], area: '' },
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
