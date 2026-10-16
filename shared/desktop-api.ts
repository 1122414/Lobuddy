import type { ChatMessage, ChatSession, ParametersByMethod, PetState, ServiceEvent, TurnState } from './desktop-protocol';

export interface Approval {
  approval_id: string; turn_id: string; session_id: string; command: string; reason: string;
}
export interface Health { protocol: number; engine: string; connected: boolean; voice_available: boolean; model_configured: boolean }
export interface Focus { state: string; seconds_remaining: number }
export interface ResultsByMethod {
  'service.health': Health;
  'session.create': ChatSession;
  'session.list': ChatSession[];
  'session.history': ChatMessage[];
  'turn.send': TurnState;
  'turn.cancel': TurnState;
  'task.list': TurnState[];
  'task.get': TurnState;
  'approval.list': Approval[];
  'approval.resolve': { accepted: boolean };
  'pet.get': PetState;
  'focus.get': Focus;
  'focus.start': Focus;
  'focus.pause': Focus;
  'focus.resume': Focus;
  'focus.stop': Focus;
}
export interface DesktopAPI {
  request<M extends keyof ParametersByMethod>(method: M, params: ParametersByMethod[M], id: string): Promise<ResultsByMethod[M]>;
  subscribe(listener: (event: ServiceEvent) => void): () => void;
  onStatus(listener: (connected: boolean) => void): () => void;
  openExternal(url: string): Promise<void>;
}
