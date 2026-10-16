import { app, BrowserWindow, dialog, ipcMain, net, protocol, session, shell } from 'electron';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';
import type { ParametersByMethod } from '../../shared/desktop-protocol';
import { assetPath, externalURL } from './policy';
import { ServiceClient } from './service-client';

protocol.registerSchemesAsPrivileged([{ scheme: 'lobuddy', privileges: { standard: true, secure: true, supportFetchAPI: true } }]);
app.enableSandbox();
const service = new ServiceClient();
service.on('diagnostic', type => console.error('Business task failed:', type));
let quitting = false;
let mainWindow: BrowserWindow | null = null;
const origin = 'lobuddy://app/index.html';
if (!app.requestSingleInstanceLock()) app.quit();

function trusted(event: Electron.IpcMainInvokeEvent): void {
  if (!mainWindow || event.sender !== mainWindow.webContents || event.senderFrame !== mainWindow.webContents.mainFrame || event.senderFrame.url !== origin) throw new Error('Untrusted sender');
}
function createWindow(): void {
  if (mainWindow) { mainWindow.show(); return; }
  const window = new BrowserWindow({
    title: 'Lobuddy', width: 1200, height: 800, minWidth: 900, minHeight: 620,
    backgroundColor: '#f8fafb', titleBarStyle: 'hiddenInset', trafficLightPosition: { x: 20, y: 18 },
    webPreferences: {
      preload: join(__dirname, 'preload.js'), contextIsolation: true, nodeIntegration: false,
      sandbox: true, webSecurity: true, webviewTag: false,
    },
  });
  mainWindow = window;
  window.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
  window.webContents.on('will-navigate', event => event.preventDefault());
  window.webContents.on('did-start-loading', () => { void service.denyApprovals(); });
  window.webContents.on('render-process-gone', () => { void service.denyApprovals(); });
  window.on('close', () => { void service.denyApprovals(); });
  window.on('closed', () => { mainWindow = null; });
  void window.loadURL(origin);
}

app.whenReady().then(async () => {
  const bundle = join(app.getAppPath(), 'dist');
  protocol.handle('lobuddy', request => {
    try { return net.fetch(pathToFileURL(assetPath(request.url, bundle)).href); }
    catch { return new Response('Not found', { status: 404 }); }
  });
  session.defaultSession.setPermissionRequestHandler((_contents, _permission, callback) => callback(false));
  session.defaultSession.setPermissionCheckHandler(() => false);
  ipcMain.handle('business:request', (event, method: keyof ParametersByMethod, params: unknown, id: string) => {
    trusted(event);
    if (['image.import', 'credential.configure'].includes(method)) throw new Error('Use native configuration entry');
    return service.request(method, params, id);
  });
  ipcMain.handle('credential:configure', (event, account: unknown) => {
    trusted(event);
    if (!['llm_api_key', 'llm_multimodal_api_key', 'fish_api_key'].includes(String(account))) throw Error('Invalid credential account');
    return service.request('credential.configure', { account }, crypto.randomUUID());
  });
  ipcMain.handle('app:restart', event => { trusted(event); app.relaunch(); app.quit(); });
  ipcMain.handle('image:pick', async event => {
    trusted(event);
    const result = await dialog.showOpenDialog(mainWindow!, { title: '选择图片', properties: ['openFile'], filters: [{ name: '图片', extensions: ['png', 'jpg', 'jpeg', 'gif', 'webp'] }] });
    if (result.canceled || !result.filePaths[0]) return null;
    trusted(event);
    return service.request('image.import', { path: result.filePaths[0] }, crypto.randomUUID());
  });
  ipcMain.handle('external:open', (event, url: unknown) => { trusted(event); return shell.openExternal(externalURL(url)); });
  service.on('event', event => { if (mainWindow && !mainWindow.isDestroyed()) mainWindow.webContents.send('business:event', event); });
  service.on('status', connected => { if (mainWindow && !mainWindow.isDestroyed()) mainWindow.webContents.send('business:status', connected); });
  const development = app.isPackaged ? JSON.parse(readFileSync(join(process.resourcesPath, 'development-runtime.json'), 'utf8')) as { root: string; python: string } : { root: join(app.getAppPath(), '..'), python: process.env.LOBUDDY_PYTHON || join(app.getAppPath(), '../.venv/bin/python') };
  const data = process.env.LOBUDDY_DATA_DIR || join(app.getPath('userData'), 'service');
  service.start(development.python, development.root, data, process.env.LOBUDDY_WORKSPACE || join(data, 'workspace'));
  createWindow();
  try { await service.handshake(); } catch { /* Health requests display the disconnected state. */ }
}).catch(() => { app.exit(1); });
app.on('second-instance', createWindow);
app.on('activate', createWindow);
app.on('window-all-closed', () => { if (process.platform !== 'darwin') app.quit(); });
app.on('before-quit', event => {
  if (quitting) return;
  event.preventDefault(); quitting = true;
  void service.denyApprovals().finally(() => service.stop()).finally(() => app.quit());
});
