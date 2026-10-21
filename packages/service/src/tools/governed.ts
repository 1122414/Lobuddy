import { join } from 'node:path';
import { ToolRequestSchema, type TurnState, type ToolRequest, type RuntimeSettings } from '@lobuddy/contracts';
import { WorkspaceFiles } from './files.js';
import { PracticalTools } from './practical.js';
import { LocalOpen, openNative } from './local.js';
import { commandArguments, runCommand } from './commands.js';
import { fetchPage } from './web.js';
import { OutcomeRepository } from '../storage/outcomes.js';
import { Approvals } from '../tasks/approvals.js';
import { forbidsCommandExecution } from '@lobuddy/domain';
type KnowledgeRequest = Extract<ToolRequest, { name: 'lobuddy_session_search' | 'lobuddy_skill_read' | 'lobuddy_memory_propose' }>;
export type KnowledgeTools = (request: KnowledgeRequest, state: TurnState, signal: AbortSignal, active: () => boolean) => Promise<string>;
export class GovernedTools {
  readonly files: WorkspaceFiles;
  readonly used: string[] = [];
  private readonly calls = new Set<string>();
  private total = 0;
  private lookups = 0;
  private shellCalls = 0;
  private readonly local: LocalOpen;
  private readonly practical: PracticalTools;
  constructor(private readonly state: TurnState, private readonly settings: RuntimeSettings,
    private readonly approvals: Approvals, outcomes: OutcomeRepository, private readonly signal: AbortSignal,
    private readonly active: () => boolean, applicationRoot: string, private readonly knowledge?: KnowledgeTools) {
    this.files = new WorkspaceFiles(settings.workspace_path, [settings.data_dir,
      ...['core','app','bridge','desktop','shared','scripts','tests','packages','qualification','migration'].map(part => join(applicationRoot, part))]);
    this.local = new LocalOpen(this.files.root);
    this.practical = new PracticalTools(this.files, outcomes, state.turn_id, (tool, command, reason) => this.approve(tool, command, reason), active, signal);
  }
  private approve(tool: string, command: string, reason: string): Promise<boolean> {
    return this.approvals.request(this.state, tool, command, reason, this.settings.hitl_approval_timeout_seconds * 1000, this.signal, this.active);
  }
  async execute(value: unknown): Promise<string> {
    const request = ToolRequestSchema.parse(value), name = request.name;
    if (this.calls.has(request.callId)) throw Error('重复工具调用被拒绝'); this.calls.add(request.callId);
    if (this.signal.aborted || !this.active() || this.total >= this.settings.execution_max_tool_calls_per_task) throw Error('工具已取消或超出预算');
    if (['lobuddy_local_resolve','lobuddy_local_open'].includes(name) && !this.settings.execution_local_tools_enabled) throw Error('本地工具未启用');
    if (name === 'lobuddy_local_resolve' && this.lookups >= this.settings.execution_max_local_lookup_calls) throw Error('本地查找超过预算');
    if (name === 'lobuddy_local_open' && this.used.includes(name)) throw Error('本轮只允许打开一次');
    if (name === 'lobuddy_exec' && (!this.settings.shell_enabled || this.shellCalls >= this.settings.execution_max_shell_calls_per_task)) throw Error('命令执行未启用或超出预算');
    this.total++; this.used.push(name);
    const limit = this.settings.execution_max_tool_result_chars;
    const clipped = (text: string) => [...text].slice(0, limit).join('');
    switch (request.name) {
      case 'lobuddy_read_file': return clipped(this.files.read(request.arguments.path));
      case 'lobuddy_write_file': {
        if (request.arguments.content === null) throw Error('缺少文件内容');
        const path = this.files.path(request.arguments.path);
        this.files.checkNoSymlink(path);
        if (!await this.approve(name, `write_file ${path}`, '创建或覆盖文件需要确认') || !this.active()) throw Error('文件写入未获批准');
        this.files.write(path, request.arguments.content); return '文件已写入。';
      }
      case 'lobuddy_web_fetch': return fetchPage(request.arguments.url, limit, this.signal);
      case 'lobuddy_web_search': return fetchPage('https://www.bing.com/search?format=rss&' + new URLSearchParams({ q: request.arguments.query }), limit, this.signal);
      case 'lobuddy_local_resolve': this.lookups++; return clipped(JSON.stringify(this.local.resolve(request.arguments.query)));
      case 'lobuddy_local_open': {
        const path = this.local.validate(request.arguments.path);
        if (!await this.approve(name, `打开 ${path}`, '确认使用系统默认应用打开此候选') || !this.active()) throw Error('本地打开未获批准');
        await openNative(this.local.validate(path), this.signal); return '已交给系统打开。';
      }
      case 'lobuddy_exec': {
        // Dedicated local opening/search must never be routed through command execution.
        if (forbidsCommandExecution(this.state.input_text)) throw Error('此请求必须使用专用查找或打开工具');
        this.shellCalls++;
        const args = commandArguments(request.arguments.command, this.files);
        if (!await this.approve(name, args.map(value => JSON.stringify(value)).join(' '), '确认在工作区运行此本地命令') || !this.active()) throw Error('命令未获批准');
        commandArguments(request.arguments.command, this.files);
        return runCommand(args, this.files.root, limit, this.settings.task_timeout * 1000, this.signal);
      }
      case 'lobuddy_organize': return this.scenario(await this.practical.organize(request.arguments), limit);
      case 'lobuddy_digest': return this.scenario(await this.practical.digest(request.arguments), limit);
      default:
        if (!this.knowledge) throw Error('知识服务尚未连接');
        return clipped(await this.knowledge(request, this.state, this.signal, this.active));
    }
  }
  private scenario(value: string, limit: number): string {
    if ([...value].length <= limit) return value;
    const payload = JSON.parse(value) as Record<string, unknown>, outcome = (payload.outcome ?? payload) as Record<string, unknown>;
    return JSON.stringify({ preview_id: payload.preview_id ?? null, count: payload.count ?? null, verdict: outcome.verdict ?? null,
      reason: outcome.reason ?? null, detail: '完整清单在审批或任务结果证据中；本条工具回复已按预算缩短。' });
  }
}
