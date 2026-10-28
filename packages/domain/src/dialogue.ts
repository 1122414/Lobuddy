import { trimUserText } from '@lobuddy/contracts';
import { REJECT_CONTEXT } from './memory.js';

const words = new Intl.Segmenter('zh', { granularity: 'word' });
function boundarySubject(text: string): string {
  const tokens = [...words.segment(text)];
  // Strip standalone sentence particles, preserving nouns such as 酒吧 and 知了.
  while (['了', '吧'].includes(tokens.at(-1)?.segment ?? '') && [...text.slice(0, tokens.at(-1)!.index)].length >= 2) {
    text = text.slice(0, tokens.pop()!.index);
  }
  return text.replace(/(?:这个话题|的话题|的事情|的事)$/u, '').trim();
}

export function dialogueIntent(input: string): {
  mode?: 'listening' | 'discussing'; boundaries: { subject: string; temporary: boolean }[];
} | undefined {
  const text = trimUserText(input);
  if (REJECT_CONTEXT.test(text) || /转述|举个例子|假使|假若|并不是|不是说|不是让|不代表/u.test(text)) return;
  let mode: 'listening' | 'discussing' | undefined;
  const boundaries: { subject: string; temporary: boolean }[] = [];
  for (const part of text.split(/[，,。！!；;\n]+/u)) {
    const clause = part.trim().replace(/^(?:请|麻烦你|拜托你?)/u, '');
    if (/^(?:先听我(?:讲|说)(?:完|一下)?(?:就好|就行)?|(?:别|不要)一直追问(?:了)?|我(?:今天|现在|这会儿)?(?:有点|很|好|太)?(?:累|烦)(?:了)?)(?:吧)?$/u.test(clause)) mode = 'listening';
    else if (/^(?:可以|现在)?(?:帮我分析|一起讨论|给我建议)(?:一下)?$/u.test(clause)) mode = 'discussing';
    const boundary = /^(?:我)?(今天|以后|今后)(?:先|暂时)?(?:不想|不愿意|不要|不|别)(?:再)?(?:聊|谈|提)(?:起|论)?(?:关于)?([^：:]{1,40}?)$/u.exec(clause);
    if (!boundary) continue;
    const subject = boundarySubject(boundary[2]!);
    if (!subject || subject === '天' || [...subject].length > 30 || /因为|但是|不过|明天|今天|以后|不想|可以|不能/u.test(subject)) continue;
    const value = { subject, temporary: boundary[1] === '今天' }, existing = boundaries.findIndex(item => item.subject === subject);
    if (existing < 0) boundaries.push(value); else boundaries[existing] = value;
  }
  return { mode, boundaries };
}
