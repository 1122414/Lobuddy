import { sanitizeMemory } from './memory.js';
import { trimUserText } from '@lobuddy/contracts';
export function validateSkill(content: string): void {
  if ([...content].length < 50 || [...content].length > 64000 || content.split(/\r\n|[\n\r\v\f\x85\u2028\u2029]/u).length > 500) throw Error('技能内容长度不符合要求');
  if (!content.startsWith('---') || !content.includes('\n---')) throw Error('缺少 SKILL.md frontmatter');
  const body = content.split('---').slice(2).join('---');
  if (!/\bwhen\s+to\s+use\b|\bwhen\s+(?:the\s+)?user\b|\buse\s+this\b|##\s*(?:trigger|when to use|usage)/iu.test(body)) throw Error('技能缺少明确触发规则');
  if (sanitizeMemory(content) !== trimUserText(content)) throw Error('技能包含秘密或敏感标识');
  if (/\b(?:rm\s+-rf|del\s+\/f|format\s+|mkfs|dd\s+if=|shutdown|reboot|poweroff)\b|\b(?:curl|wget)\s+.*\|\s*sh\b|\b(?:eval\s*\(|exec\s*\(|os\.system|subprocess\.call)|\bimport\s+subprocess/iu.test(content)) throw Error('技能包含危险命令');
}
