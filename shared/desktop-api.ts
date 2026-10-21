import type { ResultsByMethod } from '@lobuddy/contracts' with { 'resolution-mode': 'import' };
import type { SourceShare, SourceView, CompanionPreferences, ImageInfo, ParametersByMethod, ServiceEvent } from './desktop-protocol';
export type { ResultsByMethod };
export type Approval = ResultsByMethod['approval.list'][number];
export type Health = ResultsByMethod['service.health'];
export type Focus = ResultsByMethod['focus.get'];

export interface WindowStatus { shortcuts: Record<string, boolean>; petVisible: boolean }
export type WindowAction = 'chat' | 'manage' | 'hide' | 'pet' | 'drag-start' | 'drag-move' | 'drag-end';
export interface DesktopAPI {
  onVoiceStop(listener: () => void): () => void;
  voicePermission(): Promise<boolean>;
  pickSource(options: Omit<SourceShare, "kind" | "locator" | "text">): Promise<SourceView | null>;
  windowAction(action: WindowAction): Promise<void>;
  windowStatus(): Promise<WindowStatus>;
  petHitTest(interactive: boolean): Promise<void>;
  pickPet(): Promise<CompanionPreferences | null>;
  request<M extends keyof ParametersByMethod>(method: M, params: ParametersByMethod[M], id: string): Promise<ResultsByMethod[M]>;
  subscribe(listener: (event: ServiceEvent) => void): () => void;
  onStatus(listener: (connected: boolean) => void): () => void;
  openExternal(url: string): Promise<void>;
  pickImage(): Promise<ImageInfo | null>;
  configureCredential(account: 'llm_api_key' | 'llm_multimodal_api_key' | 'fish_api_key' | 'typesafe_api_key'): Promise<{ saved: boolean }>;
  restart(): Promise<void>;
}
