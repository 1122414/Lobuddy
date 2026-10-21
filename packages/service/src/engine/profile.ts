export const DISABLED_DSH_ROWS = [
  'session-log-deepseek', 'session-telemetry-otel', 'plugin-package-inventory-deepseek',
  'session-title-llm', 'agent-instructions', 'skill-filesystem', 'tool-skill', 'tool-bash',
  'tool-pwsh', 'tool-jobs', 'tool-fs', 'tool-fs-search', 'tool-web', 'tool-subagent',
  'tool-subagent-fork', 'tool-subagent-control', 'tool-subagent-list-agents', 'tool-workflow',
  'tool-todo', 'tool-goal', 'tool-ralph', 'goal-round-driver', 'plan-mode', 'command-feedback',
  'command-goal', 'command-compact',
] as const;
export function profilePatch(plugin: string) {
  return [...DISABLED_DSH_ROWS.map(id => ({ id, disabled: true })), {
    id: 'system-prompt', config: {
      personaPrefix: '你是 Lobuddy 桌面个人助手。尊重用户偏好；工具被拒绝时不要绕过审批。',
      personaSuffix: '长期记忆由 Lobuddy 管理，不自行修改用户画像或安装插件。',
    },
  }, { insert: [{ id: 'lobuddy-bridge', name: plugin }] }];
}
