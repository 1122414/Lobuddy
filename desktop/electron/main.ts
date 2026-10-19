import { powerMonitor, app, dialog, ipcMain, net, protocol, session, shell } from 'electron';
import { constants, readFileSync, realpathSync } from 'node:fs';
import { open } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import type { WindowAction } from '../../shared/desktop-api';
import { Windows } from './windows';
import { basename, dirname, join } from 'node:path';
import { pathToFileURL } from 'node:url';
import type { ParametersByMethod } from '../../shared/desktop-protocol';
import { assetPath, externalURL } from './policy';
import { ServiceClient } from './service-client';

protocol.registerSchemesAsPrivileged([{ scheme: 'lobuddy', privileges: { standard: true, secure: true, supportFetchAPI: true } }]);
app.enableSandbox();
const service = new ServiceClient();
service.on('diagnostic', type => console.error('Business task failed:', type));
let quitting = false;
let askingQuit = false;
let restarting = false;
let windows: Windows;
if (!app.requestSingleInstanceLock()) app.quit();
function trusted(event: Electron.IpcMainInvokeEvent): void { windows.trusted(event); }

app.whenReady().then(async () => {
  const bundle = join(app.getAppPath(), 'dist');
  const data = process.env.LOBUDDY_DATA_DIR || join(app.getPath('userData'), 'service');
  windows = new Windows(service, bundle, data);
  protocol.handle('lobuddy', async request => {
    const url = new URL(request.url);
    if (url.hostname === 'pet-asset') {
      if (!/^\/[a-f0-9]{64}$/.test(url.pathname) || url.search || url.username || url.password || url.port) return new Response('Not found', { status: 404 });
      const id = url.pathname.slice(1);
      try {
        const info = await service.request('companion.get', {}, crypto.randomUUID());
        if (info.image_id !== id) return new Response('Not found', { status: 404 });
        const file = await open(join(data, 'pet-images', id), constants.O_RDONLY | constants.O_NOFOLLOW);
        try {
          const stat = await file.stat();
          if (!stat.isFile() || stat.size > 5 * 1024 * 1024) throw Error('Invalid asset');
          const bytes = await file.readFile();
          if (createHash('sha256').update(bytes).digest('hex') !== id) throw Error('Invalid asset');
          const type = bytes[0] === 137 ? 'image/png' : bytes[0] === 255 ? 'image/jpeg' : bytes.toString('ascii', 0, 3) === 'GIF' ? 'image/gif' : 'image/webp';
          return new Response(bytes, { headers: { 'Content-Type': type, 'X-Content-Type-Options': 'nosniff' } });
        } finally { await file.close(); }
      } catch { return new Response('Not found', { status: 404 }); }
    }
    try { return net.fetch(pathToFileURL(assetPath(request.url, bundle)).href); }
    catch { return new Response('Not found', { status: 404 }); }
  });
  session.defaultSession.setPermissionRequestHandler((_contents, _permission, callback) => callback(false));
  session.defaultSession.setPermissionCheckHandler(() => false);
  ipcMain.handle('business:request', (event, method: keyof ParametersByMethod, params: unknown, id: string) => {
    const surface = windows.trusted(event);
    if (['notification.next', 'notification.displayed'].includes(method)) {
      if (surface !== 'pet') throw Error('Only pet owns notification delivery');
      if (!windows.senderWindow(event).isVisible()) return method === 'notification.next' ? null : { accepted: false };
    }
    if (method === 'companionship.poll' && surface !== 'pet') throw Error('Only pet receives proactive invitations');
    if (method === 'companionship.activity') {
      if (surface === 'pet' || !params || typeof params !== 'object') throw Error('Invalid activity');
      params = { ...params, client: surface === 'manage' ? 'manage' : 'quick' };
    }
    if (['source.import_file', 'runtime.power', 'companionship.trigger', 'companion.import', 'image.import', 'credential.configure'].includes(method)) throw new Error('Use native configuration entry');
    return service.request(method, params, id);
  });
  ipcMain.handle('credential:configure', (event, account: unknown) => {
    trusted(event);
    if (!['llm_api_key', 'llm_multimodal_api_key', 'fish_api_key'].includes(String(account))) throw Error('Invalid credential account');
    return service.request('credential.configure', { account }, crypto.randomUUID());
  });
  ipcMain.handle('app:restart', event => { trusted(event); restarting = true; app.relaunch(); app.quit(); });
  ipcMain.handle('window:action', (event, action: WindowAction) => windows.action(event, action));
  ipcMain.handle('window:status', event => { trusted(event); return windows.status(); });
  ipcMain.handle('pet:hit', (event, interactive: unknown) => windows.hit(event, interactive));
  ipcMain.handle('source:pick', async (event, options: unknown) => {
    trusted(event);
    if (!options || typeof options !== 'object' || Array.isArray(options)) throw Error('Invalid share scope');
    const result = await dialog.showOpenDialog(windows.senderWindow(event), { title: '分享文本文件（不超过 100 KB）', properties: ['openFile'], filters: [{ name: '文本资料', extensions: ['txt', 'md', 'csv', 'json', 'log'] }] });
    if (result.canceled || !result.filePaths[0]) return null;
    trusted(event);
    return service.request('source.import_file', { ...options, kind: 'file', text: '', locator: join(realpathSync(dirname(result.filePaths[0])), basename(result.filePaths[0])) } as ParametersByMethod['source.import_file'], crypto.randomUUID());
  });
  ipcMain.handle('pet:pick', async event => {
    trusted(event);
    const result = await dialog.showOpenDialog(windows.senderWindow(event), { title: '选择宠物图片（不超过 5 MB）', properties: ['openFile'], filters: [{ name: '图片', extensions: ['png', 'jpg', 'jpeg', 'gif', 'webp'] }] });
    if (result.canceled || !result.filePaths[0]) return null;
    trusted(event);
    return service.request('companion.import', { path: result.filePaths[0] }, crypto.randomUUID());
  });
  ipcMain.handle('image:pick', async event => {
    trusted(event);
    const result = await dialog.showOpenDialog(windows.senderWindow(event), { title: '选择图片', properties: ['openFile'], filters: [{ name: '图片', extensions: ['png', 'jpg', 'jpeg', 'gif', 'webp'] }] });
    if (result.canceled || !result.filePaths[0]) return null;
    trusted(event);
    return service.request('image.import', { path: result.filePaths[0] }, crypto.randomUUID());
  });
  ipcMain.handle('external:open', (event, url: unknown) => { trusted(event); return shell.openExternal(externalURL(url)); });
  service.on('event', event => windows.broadcast('business:event', event));
  service.on('status', connected => windows.broadcast('business:status', connected));
  const development = app.isPackaged ? JSON.parse(readFileSync(join(process.resourcesPath, 'development-runtime.json'), 'utf8')) as { root: string; python: string } : { root: join(app.getAppPath(), '..'), python: process.env.LOBUDDY_PYTHON || join(app.getAppPath(), '../.venv/bin/python') };
  service.start(development.python, development.root, data, process.env.LOBUDDY_WORKSPACE || join(data, 'workspace'));
  windows.start();
  powerMonitor.on('suspend', () => { void service.request('runtime.power', { suspended: true }, crypto.randomUUID()).catch(() => undefined); });
  powerMonitor.on('resume', () => { void service.request('runtime.power', { suspended: false }, crypto.randomUUID()).catch(() => undefined); });
  try { await service.handshake(); } catch { /* Health requests display the disconnected state. */ }
}).catch(() => { app.exit(1); });
app.on('second-instance', () => windows?.show('manage'));
app.on('activate', () => windows?.show('manage'));
app.on('window-all-closed', () => { /* Explicit quit owns shutdown; closed windows leave the tray running. */ });
app.on('before-quit', event => {
  if (quitting) return;
  event.preventDefault();
  if (askingQuit) return;
  askingQuit = true;
  void (async () => {
    let pending = 0;
    if (service.connected && !restarting) {
      try { pending = (await service.request('delegation.list', {}, crypto.randomUUID())).filter(value => !['completed', 'cancelled', 'failed'].includes(value.status || 'draft')).length; }
      catch { /* A disconnected service cannot execute unattended work. */ }
    }
    if (pending) {
      const choice = await dialog.showMessageBox({ type: 'info', title: '退出 Lobuddy', message: `还有 ${pending} 项未结束的委托`, detail: '退出后停止执行和采音。提醒将在下次启动时按逾期规则处理；结果未知的写操作不会重放。', buttons: ['退出', '留在托盘'], defaultId: 0, cancelId: 0 });
      if (choice.response !== 0) return;
    }
    quitting = true; windows?.stop();
    await service.denyApprovals(); await service.stop(); app.quit();
  })().catch(() => {
    quitting = true; windows?.stop();
    void service.stop().finally(() => app.quit());
  }).finally(() => { askingQuit = false; });
});
