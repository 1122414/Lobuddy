export type IconName = 'chat' | 'tasks' | 'plus' | 'send' | 'work' | 'stop';
const paths: Record<IconName, string> = {
  chat: 'M20 11a8 8 0 0 1-8 8H8l-5 3 1-7a8 8 0 1 1 16-4Z',
  tasks: 'M8 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V5a2 2 0 0 0-2-2H8M7 12l3 3 7-7',
  plus: 'M12 5v14M5 12h14', send: 'm3 3 18 9-18 9 4-9-4-9Zm4 9h14',
  work: 'M9 3h6l1 3 3 1 2 5-2 5-3 1-1 3H9l-1-3-3-1-2-5 2-5 3-1 1-3ZM15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z',
  stop: 'M5 5h14v14H5Z',
};
export function Icon({ name }: { name: IconName }) {
  return <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={paths[name]} /></svg>;
}
