import { resolve, sep } from 'node:path';

export function assetPath(rawURL: string, root: string): string {
  const url = new URL(rawURL);
  if (url.protocol !== 'lobuddy:' || url.hostname !== 'app' || url.username || url.password || url.port) throw new Error('Invalid origin');
  const decoded = decodeURIComponent(url.pathname);
  if (decoded.includes('\0') || decoded.includes('\\')) throw new Error('Invalid asset');
  const file = resolve(root, '.' + (decoded === '/' ? '/index.html' : decoded));
  if (!file.startsWith(resolve(root) + sep)) throw new Error('Invalid asset');
  return file;
}
export function externalURL(raw: unknown): string {
  if (typeof raw !== 'string' || raw.length > 8192) throw new Error('Invalid URL');
  const url = new URL(raw);
  if (!['https:', 'http:'].includes(url.protocol) || url.username || url.password) throw new Error('Unsupported URL');
  return url.href;
}
export function fingerprint(method: string, params: unknown): string {
  return JSON.stringify({ method, params });
}
