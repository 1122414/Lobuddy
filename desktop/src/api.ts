import type { DesktopAPI } from '../../shared/desktop-api';
import type { ParametersByMethod } from '../../shared/desktop-protocol';

declare global { interface Window { lobuddy?: DesktopAPI } }
export function request<M extends keyof ParametersByMethod>(method: M, params: ParametersByMethod[M], id = crypto.randomUUID()) {
  if (!window.lobuddy) return Promise.reject(new Error('请在 Lobuddy 桌面应用中使用此功能。'));
  return window.lobuddy.request(method, params, id);
}
export function errorText(error: unknown): string {
  return error instanceof Error ? error.message.replace(/^Error invoking remote method '[^']+': Error: /, '') : '操作未完成，请稍后重试。';
}
