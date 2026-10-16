export type IconName = 'chat' | 'tasks' | 'plus' | 'send' | 'work' | 'stop' | 'memory' | 'skills' | 'history' | 'progress' | 'settings';
const paths: Record<IconName, string> = {
  progress: 'M4 20V10m8 10V4m8 16v-7M2 20h20',
  settings: 'M4 7h16M4 17h16M9 4v6m6 4v6',
  memory: 'M12 21s-9-5-9-12a5 5 0 0 1 9-3 5 5 0 0 1 9 3c0 7-9 12-9 12Z',
  skills: 'm12 3 3 6 6 3-6 3-3 6-3-6-6-3 6-3 3-6Z',
  history: 'M3 11a9 9 0 1 1 3 8M3 4v7h7M12 7v5l4 2',
  chat: 'M20 11a8 8 0 0 1-8 8H8l-5 3 1-7a8 8 0 1 1 16-4Z',
  tasks: 'M8 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V5a2 2 0 0 0-2-2H8M7 12l3 3 7-7',
  plus: 'M12 5v14M5 12h14', send: 'm3 3 18 9-18 9 4-9-4-9Zm4 9h14',
  work: 'M9 3h6l1 3 3 1 2 5-2 5-3 1-1 3H9l-1-3-3-1-2-5 2-5 3-1 1-3ZM15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z',
  stop: 'M5 5h14v14H5Z',
};
export function Icon({ name }: { name: IconName }) {
  return <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={paths[name]} /></svg>;
}
