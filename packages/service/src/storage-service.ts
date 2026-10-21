import { randomUUID } from 'node:crypto';
import { join } from 'node:path';
import { ChatSessionSchema } from '@lobuddy/contracts';
import { Store } from './storage/database.js';
import { ChatRepository } from './storage/chat.js';
import { PetRepository } from './storage/pet.js';
import { SettingsRepository, runtimeSettings } from './config/settings.js';
import type { Handlers } from './rpc-server.js';
export function createStorageService(options: { data: string; workspace: string; logs: string; create?: boolean }) {
  const store = new Store(join(options.data, 'lobuddy.db'), { create: options.create });
  try {
    const chat = new ChatRepository(store), pet = new PetRepository(store);
    const settings = new SettingsRepository(store, runtimeSettings(options));
    const handlers: Handlers = {
      'service.health': () => ({ protocol: 2, engine: 'ts-unconfigured', connected: false, voice_available: false, model_configured: false }),
      'settings.get': () => settings.view(), 'settings.patch': params => settings.patch(params),
      'pet.get': () => pet.getOrCreate(),
      'session.create': params => {
        const session = ChatSessionSchema.parse({ id: randomUUID(), title: params.title }); chat.saveSession(session); return session;
      },
      'session.list': params => chat.sessions(params.limit),
      'session.history': params => chat.messages(params.session_id),
    };
    return { handlers, store, settings, close: () => store.close() };
  } catch (error) { store.close(); throw error; }
}
