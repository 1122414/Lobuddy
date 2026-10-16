import type { RelationView, RelationPolicy } from "./desktop-protocol";
import type { LearningView } from "./desktop-protocol";
import type { CompanionPolicy, CompanionNotice, ThemeView, ThemeSave, CompanionPreferences, ImageInfo, SettingsView, ProgressOverview, MemoryItem, ConversationSummary, SessionSearchResponse, SkillRecord, SkillCandidate, SkillDetail } from "./desktop-protocol";
import type { ChatMessage, ChatSession, ParametersByMethod, PetState, ServiceEvent, TurnState } from './desktop-protocol';

export interface Approval {
  approval_id: string; turn_id: string; session_id: string; command: string; reason: string;
}
export interface Health { protocol: number; engine: string; connected: boolean; voice_available: boolean; model_configured: boolean }
export interface Focus { completed_count?: number; state: string; seconds_remaining: number }
export interface ResultsByMethod {
  'relationship.list': RelationView[];
  'relationship.sources': ChatMessage[];
  'relationship.resolve': RelationView;
  'relationship.edit': RelationView;
  'relationship.forget': { forgotten: boolean };
  'relationship.policy': RelationPolicy;
  'relationship.configure': RelationPolicy;
  'learning.get': LearningView;
  'learning.configure': LearningView;
  'companionship.get': CompanionPolicy;
  'companionship.configure': CompanionPolicy;
  'companionship.activity': { accepted: boolean };
  'companionship.trigger': { accepted: boolean };
  'companionship.poll': CompanionNotice | null;
  'companionship.feedback': { accepted: boolean };
  'preference.save': MemoryItem | null;
  'theme.list': ThemeView[];
  'theme.save': ThemeView;
  'theme.apply': { applied: boolean };
  'theme.delete': { deleted: boolean };
  'theme.from_image': ThemeSave;
  'companion.get': CompanionPreferences;
  'companion.save': CompanionPreferences;
  'companion.import': CompanionPreferences;
  'image.import': ImageInfo;
  'image.get': ImageInfo;
  'memory.list': MemoryItem[];
  'memory.save': MemoryItem;
  'memory.delete': { deleted: boolean };
  'history.search': SessionSearchResponse;
  'history.summaries': ConversationSummary[];
  'skill.list': SkillRecord[];
  'skill.get': SkillDetail;
  'skill.save': SkillRecord;
  'skill.toggle': { changed: boolean };
  'skill.archive': { changed: boolean };
  'skill.candidates': SkillCandidate[];
  'skill.candidate.resolve': { changed: boolean };
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
  'progress.get': ProgressOverview;
  'credential.configure': { saved: boolean };
  'settings.get': SettingsView;
  'settings.patch': SettingsView;
  'focus.get': Focus;
  'focus.start': Focus;
  'focus.pause': Focus;
  'focus.resume': Focus;
  'focus.stop': Focus;
}
export interface WindowStatus { shortcuts: Record<string, boolean>; petVisible: boolean }
export type WindowAction = 'chat' | 'manage' | 'hide' | 'pet' | 'drag-start' | 'drag-move' | 'drag-end';
export interface DesktopAPI {
  windowAction(action: WindowAction): Promise<void>;
  windowStatus(): Promise<WindowStatus>;
  petHitTest(interactive: boolean): Promise<void>;
  pickPet(): Promise<CompanionPreferences | null>;
  request<M extends keyof ParametersByMethod>(method: M, params: ParametersByMethod[M], id: string): Promise<ResultsByMethod[M]>;
  subscribe(listener: (event: ServiceEvent) => void): () => void;
  onStatus(listener: (connected: boolean) => void): () => void;
  openExternal(url: string): Promise<void>;
  pickImage(): Promise<ImageInfo | null>;
  configureCredential(account: 'llm_api_key' | 'llm_multimodal_api_key' | 'fish_api_key'): Promise<{ saved: boolean }>;
  restart(): Promise<void>;
}
