import { z } from 'zod';
import { careWindow } from '@lobuddy/domain';
import type { CompanionNotice, TurnState } from '@lobuddy/contracts';
import { parseStoredJson } from '../storage/json.js';
import { CareService } from './care.js';
import { CompanionDialogue } from './dialogue.js';
import { Companionship } from './policy.js';

const deliverySchema = z.strictObject({ notice_id: z.string(),source_id: z.string(),revision: z.string(),
  kind: z.enum(['care','news','topic']),at: z.number().finite(),day: z.string(),opened: z.boolean(),dismissed: z.boolean(),responded: z.boolean() });
type Delivery = z.infer<typeof deliverySchema>;
/** The trusted pet poll establishes a short delivery lease; model work never depends on OS-wide activity. */
export class CareDelivery {
  private visibleUntil = 0;
  private nextCheck = 0;
  suspended = false;
  constructor(readonly care: CareService,readonly dialogue: CompanionDialogue,readonly companion: Companionship,private readonly quiet: () => boolean) {
    companion.managedDelivery = true;
    companion.mayDeliver = () => this.available();
    companion.noticeValid = id => Boolean(dialogue.source(id));
    companion.topicsRevision = id => dialogue.source(id)?.revision ?? '';
    companion.dayAt = now => this.day(now);
    companion.recordPresentation = notice => this.present(notice);
    companion.recordFeedback = (notice,action) => this.feedback(notice,action);
    dialogue.externalMaterial = id => id.startsWith('care:') ? care.material(id.slice(5)) : undefined;
    dialogue.invitations.externalCandidates = () => this.candidates();
    dialogue.invitations.mayPrepare = () => this.available();
  }
  day(now = this.care.clock()): string { return new Intl.DateTimeFormat('en-CA',{timeZone: this.care.policy.timezone}).format(new Date(now * 1000)); }
  available(): boolean { const policy = this.care.policy; return !this.suspended && this.visibleUntil > this.care.clock() && careWindow(this.care.clock(),policy.timezone,policy.start_hour,policy.end_hour) && !this.quiet() && !this.companion.engaged; }
  poll(): void { this.visibleUntil = this.care.clock() + 3; }
  hide(): void { this.visibleUntil = 0; this.dialogue.clear(); }
  private read(id: string): Delivery | undefined {
    const row = this.care.store.connection.prepare('SELECT body FROM companion_delivery WHERE notice_id=?').get(id);
    return row ? deliverySchema.parse(parseStoredJson(String(row.body))) : undefined;
  }
  private save(value: Delivery): void {
    this.care.store.run('INSERT INTO companion_delivery VALUES(?,?) ON CONFLICT(notice_id) DO UPDATE SET body=excluded.body',value.notice_id,JSON.stringify(deliverySchema.parse(value)));
  }
  candidates() {
    return this.care.due().filter(item => item.unanswered < 2 && !this.dialogue.blocked(this.care.fact(item),Boolean(item.project_id))).map(item => ({
      source_id: `care:${item.id}`,revision: item.source_revision,title: item.title,category: 'care',created_at: this.care.sourceTime(item.source_id).at,material: this.care.fact(item),
      source_time:this.care.sourceTimeLabel(item.source_id),now_time:new Date(this.care.clock()*1000).toLocaleString('zh-CN',{timeZone:this.care.policy.timezone,hour12:false})+` (${this.care.policy.timezone})`,
    }));
  }
  tick(): void {
    if (!this.available() || !this.companion.policy.enabled || this.companion.policy.do_not_disturb) return;
    const now = this.care.clock(); if (now < this.nextCheck) return; this.nextCheck = now + 60;
    for (const item of this.care.due()) if (item.unanswered >= 2) this.care.unanswered(item.id);
    if (this.candidates().length) this.companion.trigger({event:'care_due'});
  }
  private present(notice: CompanionNotice): void {
    if (!this.available()) throw Error('当前不适合显示这句话');
    const source = this.dialogue.source(notice.memory_id); if (!source) throw Error('来源已失效');
    const kind = notice.memory_id.startsWith('care:') ? 'care' : notice.memory_id.startsWith('news:') ? 'news' : 'topic';
    if (kind === 'care') this.care.presented(notice.memory_id.slice(5));
    this.save({notice_id: notice.notice_id,source_id: notice.memory_id,revision: source.revision,kind,at: this.care.clock(),day: this.day(),opened:false,dismissed:false,responded:false});
  }
  private feedback(notice: CompanionNotice, action: string): void {
    const record = this.read(notice.notice_id); if (!record) return;
    if (action === 'opened') record.opened = true;
    else record.dismissed = true;
    this.save(record);
    if (record.kind === 'care' && ['ignored','later'].includes(action)) this.care.unanswered(record.source_id.slice(5));
    if (record.kind === 'care' && action === 'never') {
      const item = this.care.get(record.source_id.slice(5)); if (item) this.care.update({id:item.id,revision:item.revision,action:'pause'});
    }
  }
  respond(state: TurnState): void {
    const row = this.care.store.connection.prepare("SELECT notice_id,source_id FROM companion_handoff WHERE session_id=? AND status='active' ORDER BY accepted_at DESC,rowid DESC LIMIT 1").get(state.session_id);
    if (!row || !String(row.source_id).startsWith('care:')) return;
    if (this.care.respond(String(row.source_id).slice(5),state.turn_id)) {
      const record = this.read(String(row.notice_id)); if (record) {record.responded = true; this.save(record);}
    }
  }
}
