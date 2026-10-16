import { contextBridge, ipcRenderer } from 'electron';
import type { DesktopAPI } from '../../shared/desktop-api';
import type { ServiceEvent } from '../../shared/desktop-protocol';

const api: DesktopAPI = {
  request: (method, params, id) => ipcRenderer.invoke('business:request', method, params, id),
  subscribe: listener => {
    const handler = (_event: Electron.IpcRendererEvent, event: ServiceEvent) => listener(event);
    ipcRenderer.on('business:event', handler);
    return () => { ipcRenderer.removeListener('business:event', handler); };
  },
  onStatus: listener => {
    const handler = (_event: Electron.IpcRendererEvent, connected: boolean) => listener(connected);
    ipcRenderer.on('business:status', handler);
    return () => { ipcRenderer.removeListener('business:status', handler); };
  },
  openExternal: url => ipcRenderer.invoke('external:open', url),
};
contextBridge.exposeInMainWorld('lobuddy', api);
