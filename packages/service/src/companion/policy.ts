import { randomUUID } from 'node:crypto';
import { CompanionPolicySchema, CompanionPolicyStateSchema, trimUserText, type CompanionPolicy,
  type CompanionActivity, type CompanionTrigger, type CompanionFeedback, type TopicChoice } from '@lobuddy/contracts';
import { Store } from '../storage/database.js';
import { Preferences } from '../storage/preferences.js';
import { TopicService } from './topics.js';
export function proactiveInstruction(text: string): boolean | undefined {
  const value = trimUserText(text).replace(/[。！!.]+$/u, '');
  if (/^(?:以后|今后|现在)?(?:请)?(?:不要|别)(?:再)?(?:主动找我(?:聊天|说话)?|主动打扰我|打扰我)(?![\s\S])/u.test(value)) return false;
  if (/^(?:以后|现在)?(?:可以|允许你)(?:主动找我(?:聊天|说话)?|主动和我聊天)(?![\s\S])/u.test(value)) return true;
  return;
}
export class Companionship {
  readonly preferences: Preferences;
  readonly topics: TopicService;
  policy: CompanionPolicy;
  state: ReturnType<typeof CompanionPolicyStateSchema.parse>;
  private activity = new Map<string, { at: number; value: CompanionActivity }>();
  activityVersion = 0;
  selectTopic: () => TopicChoice | undefined;
  waitPreparation = () => false;
  deferUntil: () => number | undefined = () => undefined;
  managedDelivery = false;
  mayDeliver = () => true;
  noticeValid = (_id: string) => true;
  dayAt?: (now: number) => string;
  recordPresentation = (_notice: NonNullable<Companionship['state']['notice']>) => {};
  recordFeedback = (_notice: NonNullable<Companionship['state']['notice']>,_action: string) => {};
  constructor(readonly store: Store, readonly clock = () => Date.now() / 1000) {
    this.preferences = new Preferences(store); this.topics = new TopicService(store, clock);
    this.policy = CompanionPolicySchema.parse(this.preferences.json('companion_policy'));
    this.state = CompanionPolicyStateSchema.parse(this.preferences.json('companion_policy_state'));
    this.selectTopic = () => this.topics.choose();
    if (this.state.notice) {
      this.state.cooldown_until = Math.max(this.state.cooldown_until, this.state.last_shown + this.policy.ignore_minutes * 60);
      this.state.notice = null; this.save();
    }
  }
  save(): void { this.preferences.set('companion_policy_state', JSON.stringify(this.state)); }
  configure(input: CompanionPolicy): CompanionPolicy {
    this.policy = CompanionPolicySchema.parse(input); this.preferences.set('companion_policy', JSON.stringify(this.policy));
    if (!this.policy.enabled || this.policy.do_not_disturb || !this.policy.daily_limit) {
      this.state.notice = null; this.state.pending = ''; this.save();
    }
    return this.policy;
  }
  engage(value: CompanionActivity): void {
    if (value.typing || value.conversation) this.activityVersion++;
    this.activity.set(value.client, { at: this.clock(), value });
    if ((value.typing || value.conversation) && this.state.notice) this.feedback({ notice_id: this.state.notice.notice_id, action: 'opened' });
  }
  get engaged(): boolean {
    return [...this.activity.values()].some(item => this.clock() - item.at < 10 && (item.value.typing || item.value.conversation));
  }
  trigger(value: CompanionTrigger | { event: 'care_due' | 'news_due' }): void {
    const now = this.clock(); if (this.state.notice || this.state.pending || now < this.state.cooldown_until) return;
    this.state.pending = value.event; this.state.pending_at = now + 30; this.state.pending_expires = now + 1800; this.save();
  }
  feedback(value: CompanionFeedback): void {
    const notice = this.state.notice; if (!notice || notice.notice_id !== value.notice_id) return;
    this.recordFeedback(notice,value.action);
    if (notice.topic_id) this.topics.feedback(notice.topic_id, value.action);
    this.state.notice = null; this.state.pending = '';
    if (['ignored','later','never'].includes(value.action)) this.state.cooldown_until = this.clock() + this.policy.ignore_minutes * 60;
    this.save();
  }
  respond(text: string): void {
    this.activityVersion++;
    const value = trimUserText(text).replace(/[。！!]+$/u, '');
    const match = /^(?:以后|今后)(?:别提|不要提)([^？?\n「」“”"]{1,40})(?![\s\S])/u.exec(value);
    if (match) this.topics.blockMatching(match[1]!);
    else if (!['暂时不聊','稍后再聊','以后别提','以后不要提'].includes(value)) return;
    else this.topics.feedback(this.state.last_topic_id, value.startsWith('以后') ? 'never' : 'later');
    this.state.cooldown_until = this.clock() + this.policy.ignore_minutes * 60;
    this.state.notice = null; this.state.pending = ''; this.save();
  }
  poll(focused: boolean, running: boolean) {
    const now = this.clock(), date = new Date(now * 1000);
    const day = this.dayAt?.(now) ?? `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2,'0')}-${String(date.getDate()).padStart(2,'0')}`;
    if (day > this.state.day) { this.state.day = day; this.state.used = 0; this.save(); }
    if (this.state.notice?.memory_id && !(this.managedDelivery ? this.noticeValid(this.state.notice.memory_id) : this.topics.valid(this.state.notice.memory_id))) {
      this.state.notice = null; this.state.pending = ''; this.save();
    }
    if (this.state.notice && now >= this.state.notice.expires_at) this.feedback({ notice_id: this.state.notice.notice_id, action: 'ignored' });
    const engaged = [...this.activity.values()].some(item => now - item.at < 10 && (item.value.typing || item.value.conversation));
    if (!this.policy.enabled || this.policy.do_not_disturb || focused || running || engaged || !this.mayDeliver()) {
      if (this.state.notice) { this.state.notice = null; this.save(); } return null;
    }
    if (this.state.notice) return this.state.notice;
    if (this.state.pending && now > this.state.pending_expires) { this.state.pending = ''; this.save(); }
    if (!this.state.pending || now < this.state.pending_at || this.state.used >= this.policy.daily_limit ||
      now < this.state.cooldown_until || now - this.state.last_shown < this.policy.interval_minutes * 60 || this.waitPreparation()) return null;
    const topic = this.selectTopic();
    if (!topic) {
      const until = this.deferUntil();
      if (until !== undefined && until < this.state.pending_expires) this.state.pending_at = Math.max(now + 1, until);
      else this.state.pending = '';
      this.save(); return null;
    }
    if (!this.managedDelivery) { this.topics.shown(topic); this.state.last_topic_id = topic.topic_id; }
    this.state.notice = { notice_id: randomUUID(), text: topic.text,
      source: this.state.pending, expires_at: now + 20, topic_id: topic.topic_id, memory_id: topic.memory_id };
    if (!this.managedDelivery) { this.state.used++; this.state.last_shown = now; }
    this.state.pending = ''; this.save(); return this.state.notice;
  }
  presented(id: string): boolean {
    const notice = this.state.notice,now = this.clock();
    if (!this.managedDelivery || !notice || notice.notice_id !== id || notice.expires_at <= now || !this.mayDeliver() ||
      !this.policy.enabled || this.policy.do_not_disturb || this.engaged || notice.memory_id && !this.noticeValid(notice.memory_id)) return false;
    if (this.store.connection.prepare('SELECT 1 FROM companion_delivery WHERE notice_id=?').get(id)) return true;
    if (this.state.used >= this.policy.daily_limit || now - this.state.last_shown < this.policy.interval_minutes * 60) return false;
    const previous = structuredClone(this.state);
    try {
      this.store.transaction(() => {
        this.recordPresentation(notice);
        this.topics.shown({topic_id: notice.topic_id,memory_id: notice.memory_id,revision: this.topics.externalValid ? this.topicsRevision(notice.memory_id) : '',text: notice.text});
        this.state.used++; this.state.last_shown = now; this.state.last_topic_id = notice.topic_id; this.save();
      });
    } catch (error) { this.state = previous; throw error; }
    return true;
  }
  topicsRevision = (_id: string) => '';
}
