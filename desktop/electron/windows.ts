import { app, BrowserWindow, globalShortcut, Menu, nativeImage, screen, Tray } from 'electron';
import { mkdirSync, readFileSync, renameSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import type { CompanionPreferences } from '../../shared/desktop-protocol';
import type { WindowAction, WindowStatus } from '../../shared/desktop-api';
import { clampWindow, chatBounds, type Rect } from './geometry';
import { ServiceClient } from './service-client';

type Surface = 'manage' | 'quick' | 'pet';
export const windowURL = (surface: Surface) => 'lobuddy://app/index.html' + (surface === 'manage' ? '' : `?surface=${surface}`);

export class Windows {
  private windows = new Map<Surface, BrowserWindow>();
  private tray?: Tray;
  private timer?: ReturnType<typeof setInterval>;
  private refreshing = false;
  private preferences?: CompanionPreferences;
  private focusState = 'idle';
  private drag?: { cursor: Electron.Point; bounds: Rect };
  private shortcuts: Record<string, boolean> = {};
  private readonly stateFile: string;
  constructor(private service: ServiceClient, private bundle: string, data: string) {
    this.stateFile = join(data, 'window-state.json');
  }
  private areas() { return screen.getAllDisplays().map(display => display.workArea); }
  private petBounds(): Rect {
    const area = screen.getPrimaryDisplay().workArea;
    let bounds = { x: area.x + area.width - 290, y: area.y + area.height - 330, width: 260, height: 300 };
    try {
      const saved: unknown = JSON.parse(readFileSync(this.stateFile, 'utf8'));
      if (saved && typeof saved === 'object' && 'x' in saved && 'y' in saved && typeof saved.x === 'number' && typeof saved.y === 'number' && Number.isFinite(saved.x) && Number.isFinite(saved.y)) bounds = { ...bounds, x: saved.x, y: saved.y };
    } catch { /* First run or interrupted save: use visible default. */ }
    return clampWindow(bounds, this.areas());
  }
  private savePosition() {
    const pet = this.windows.get('pet');
    if (!pet || pet.isDestroyed()) return;
    const { x, y } = pet.getBounds();
    mkdirSync(dirname(this.stateFile), { recursive: true });
    writeFileSync(this.stateFile + '.tmp', JSON.stringify({ x, y }), { mode: 0o600 });
    renameSync(this.stateFile + '.tmp', this.stateFile);
  }
  trusted(event: Electron.IpcMainInvokeEvent): Surface {
    for (const [surface, window] of this.windows) {
      if (!window.isDestroyed() && event.sender === window.webContents && event.senderFrame === window.webContents.mainFrame && event.senderFrame.url === windowURL(surface)) return surface;
    }
    throw Error('Untrusted sender');
  }
  senderWindow(event: Electron.IpcMainInvokeEvent): BrowserWindow { return this.windows.get(this.trusted(event))!; }
  broadcast(channel: string, value: unknown) {
    for (const window of this.windows.values()) if (!window.isDestroyed()) window.webContents.send(channel, value);
  }
  show(surface: Surface): BrowserWindow {
    let window = this.windows.get(surface);
    if (window) {
      if (surface === 'pet') window.showInactive();
      else { if (surface === 'quick') window.setBounds(chatBounds(this.show('pet').getBounds(), this.areas())); window.show(); window.focus(); }
      return window;
    }
    const manage = surface === 'manage', pet = surface === 'pet';
    const geometry = pet ? this.petBounds() : surface === 'quick' ? chatBounds(this.show('pet').getBounds(), this.areas()) : { width: 1200, height: 800 };
    window = new BrowserWindow({
      title: manage ? 'Lobuddy' : pet ? 'Lobuddy 桌宠' : 'Lobuddy 快速聊天', ...geometry,
      minWidth: manage ? 900 : undefined, minHeight: manage ? 620 : undefined,
      frame: manage, transparent: !manage, backgroundColor: manage ? '#f8fafb' : '#00000000',
      titleBarStyle: manage ? 'hiddenInset' : undefined, trafficLightPosition: manage ? { x: 20, y: 18 } : undefined,
      resizable: manage, maximizable: manage, fullscreenable: manage, focusable: !pet,
      skipTaskbar: !manage, alwaysOnTop: !manage, hasShadow: !pet, show: false,
      webPreferences: { preload: join(__dirname, 'preload.js'), contextIsolation: true, nodeIntegration: false, sandbox: true, webSecurity: true, webviewTag: false },
    });
    if (pet) this.preferences = undefined;
    const owned = window;
    this.windows.set(surface, window);
    window.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
    window.webContents.on('will-navigate', event => event.preventDefault());
    let loaded = false;
    window.webContents.on('did-start-loading', () => { if (loaded) void this.service.denyApprovals(); });
    window.webContents.on('did-finish-load', () => { loaded = true; });
    window.webContents.on('render-process-gone', () => { void this.service.denyApprovals(); });
    window.on('close', () => { void this.service.denyApprovals(); if (pet) this.savePosition(); });
    window.on('closed', () => { this.windows.delete(surface); });
    window.once('ready-to-show', () => { if (pet) { owned.showInactive(); void this.refresh(); } else owned.show(); });
    if (pet) { window.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true }); window.setIgnoreMouseEvents(true, { forward: true }); }
    void window.loadURL(windowURL(surface));
    return window;
  }
  hit(event: Electron.IpcMainInvokeEvent, interactive: unknown) {
    if (this.trusted(event) !== 'pet' || typeof interactive !== 'boolean') throw Error('Invalid hit test');
    this.windows.get('pet')!.setIgnoreMouseEvents(!interactive, { forward: true });
  }
  action(event: Electron.IpcMainInvokeEvent, action: WindowAction) {
    const surface = this.trusted(event);
    switch (action) {
      case 'chat': this.show('quick'); break;
      case 'manage': this.show('manage'); break;
      case 'pet': this.show('pet'); break;
      case 'hide': this.windows.get(surface)!.hide(); void this.service.denyApprovals(); break;
      case 'drag-start':
        if (surface !== 'pet') throw Error('Only pet can drag');
        this.drag = { cursor: screen.getCursorScreenPoint(), bounds: this.windows.get('pet')!.getBounds() }; break;
      case 'drag-move':
        if (surface !== 'pet' || !this.drag) return;
        { const cursor = screen.getCursorScreenPoint(); this.windows.get('pet')!.setBounds(clampWindow({ ...this.drag.bounds, x: this.drag.bounds.x + cursor.x - this.drag.cursor.x, y: this.drag.bounds.y + cursor.y - this.drag.cursor.y }, this.areas())); } break;
      case 'drag-end':
        if (surface !== 'pet') throw Error('Only pet can drag');
        this.drag = undefined; this.savePosition(); break;
      default: throw Error('Invalid window action');
    }
  }
  status(): WindowStatus { return { shortcuts: this.shortcuts, petVisible: this.windows.get('pet')?.isVisible() ?? false }; }
  private async focusToggle() {
    const method = this.focusState === 'focusing' ? 'focus.pause' : this.focusState === 'paused' ? 'focus.resume' : 'focus.start';
    try { await this.service.request(method, method === 'focus.start' ? { minutes: 25 } : {}, crypto.randomUUID()); await this.refresh(); }
    catch { this.show('manage'); }
  }
  private menu() {
    this.tray?.setContextMenu(Menu.buildFromTemplate([
      { label: '快速聊天', click: () => this.show('quick') }, { label: '管理窗口', click: () => this.show('manage') },
      { label: this.focusState === 'focusing' ? '暂停专注' : this.focusState === 'paused' ? '继续专注' : '开始专注 · 25 分钟', click: () => { void this.focusToggle(); } },
      { label: '显示桌宠', click: () => this.show('pet') }, { type: 'separator' }, { label: '退出 Lobuddy', click: () => app.quit() },
    ]));
  }
  private async refresh() {
    if (this.refreshing) return;
    this.refreshing = true;
    try {
      const [preferences, focus] = await Promise.all([this.service.request('companion.get', {}, crypto.randomUUID()), this.service.request('focus.get', {}, crypto.randomUUID())]);
      if (this.focusState !== focus.state) { this.focusState = focus.state; this.menu(); }
      const pet = this.windows.get('pet');
      if (pet && JSON.stringify(preferences) !== JSON.stringify(this.preferences)) {
        this.preferences = preferences;
        const scale = preferences.scale ?? 1;
        pet.setBounds(clampWindow({ ...pet.getBounds(), width: Math.max(260, Math.round(192 * scale + 40)), height: Math.round(180 * scale + 120) }, this.areas()));
        pet.setAlwaysOnTop(preferences.always_on_top ?? true);
      }
    } catch { /* Renderers expose service errors; never start another runtime. */ }
    finally { this.refreshing = false; }
  }
  start() {
    const manage = this.show('manage');
    manage.webContents.once('did-finish-load', () => this.show('pet'));
    const icon = nativeImage.createFromPath(join(this.bundle, 'tray.png')).resize({ width: 18, height: 18 });
    this.tray = new Tray(icon); this.tray.setToolTip('Lobuddy'); this.menu();
    this.tray.on('click', () => this.show('quick'));
    for (const [key, action] of Object.entries({ 'CommandOrControl+Alt+Space': () => this.show('quick'), 'CommandOrControl+Alt+L': () => this.show('manage'), 'CommandOrControl+Alt+F': () => { void this.focusToggle(); } })) this.shortcuts[key] = globalShortcut.register(key, action);
    const reposition = () => { const pet = this.windows.get('pet'); if (pet) { pet.setBounds(clampWindow(pet.getBounds(), this.areas())); this.savePosition(); } const quick = this.windows.get('quick'); if (quick) quick.setBounds(clampWindow(quick.getBounds(), this.areas())); };
    screen.on('display-removed', reposition); screen.on('display-metrics-changed', reposition);
    this.timer = setInterval(() => { void this.refresh(); }, 1000);
  }
  stop() { clearInterval(this.timer); this.savePosition(); globalShortcut.unregisterAll(); this.tray?.destroy(); }
}
