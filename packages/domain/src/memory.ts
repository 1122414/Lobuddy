import { createHash } from 'node:crypto';
import { trimUserText } from '@lobuddy/contracts';
import { CASEFOLD } from './casefold-data.js';

export const REJECT_CONTEXT = /[“”「」『』"`]|如果|假如|假设|角色扮演|举例|例如|他说|她说|朋友说|不要记|别记|不必记|不要保存|别保存|[？?]/u;
export const SENSITIVE = /病|药|醫|医|诊|健康|抑郁|焦虑症|余额|工资|收入|存款|欠款|银行卡|住址|住在|身份证|手机号|电话|性癖|性生活|伴侣|男朋友|女朋友|老公|老婆|前任/u;
export const EXPLICIT = /^(?:请记住[：:,，]?|记住[：:,，]?)?(?:我(?:现在|目前|更)?(?:喜欢|不喜欢|偏好|习惯|叫|是|平时)|请叫我|以后|今后|别一直追问|少说一点|先听我讲)/u;
export const SECRETS = /密码|密钥|口令|api[ _-]?key|password|secret|bearer\s|access[ _-]?token/iu;
export const TEMPORARY = /^(?:今天|现在|刚才|这次|这一轮|暂时).*(?:累|烦|心情|回答|回复|说话|叫我)/u;
export const codepointSlice = (value: string, maximum: number) => [...value].slice(0, maximum).join('');
export const casefold = (value: string) => [...value].map(character => CASEFOLD[character.codePointAt(0)!] ?? character).join('');
export const memoryDigest = (value: string) => createHash('sha256').update(casefold(trimUserText(value))).digest('hex');
export function sanitizeMemory(value: string): string {
  for (const pattern of [/sk-[a-zA-Z0-9]{20,}/g, /ghp_[a-zA-Z0-9]{36}/g, /xoxb-[a-zA-Z0-9-]+/g,
    /Bearer\s+[a-zA-Z0-9._-]+/g, /[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}/g]) {
    value = value.replace(pattern, '[REDACTED]');
  }
  return trimUserText(value);
}
export function stableIdentity(name: string): string {
  const hash = createHash('sha1').update(Buffer.from('6ba7b8119dad11d180b400c04fd430c8', 'hex')).update(name).digest();
  hash[6] = (hash[6]! & 15) | 80; hash[8] = (hash[8]! & 63) | 128;
  const hex = hash.subarray(0, 16).toString('hex');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}
// Python sorts Unicode scalar values; JS defaults to UTF-16 code units.
export function unicodeCompare(left: string, right: string): number {
  const a = [...left], b = [...right];
  for (let i = 0; i < Math.min(a.length, b.length); i++) {
    const difference = a[i]!.codePointAt(0)! - b[i]!.codePointAt(0)!;
    if (difference) return difference;
  }
  return a.length - b.length;
}

const recallSegmenter = new Intl.Segmenter('zh', { granularity: 'word' });
const recallStopWords = new Set(('我 你 他 她 的 了 吗 呢 啊 有 还 先 跟 与 在 是 把 从 及 对 向 到 用 和 来 去 再 就 也 都 很 被 给 让 将 为 以 想 比 更 不 ' +
  '我们 你们 他们 这个 那个 什么 怎么 怎样 如何 是否 为什么 请问 ' +
  '上次 之前 以前 现在 今天 后来 然后 刚才 还记得 记得 知道 想知道 说说 一下 可以 帮我 ' +
  '项目 事情 方案 决定 选择 情况 进展 相关 关于 the a an and or is are was were what how when ' +
  'did do does we you i it this that before after last please project decision').split(' '));

/** Bounded lexical evidence, not a guess about a vague follow-up's subject. */
export function memoryQueryTerms(input: string): string[] {
  const terms: string[] = []; let singleHan = '';
  const add = (word: string) => {
    const size = [...word].length;
    if (size >= 2 && size <= 48 && !recallStopWords.has(word) && !terms.includes(word)) terms.push(word);
  };
  const flush = () => { if (singleHan.length > 1) add(singleHan); singleHan = ''; };
  for (const part of recallSegmenter.segment(casefold(codepointSlice(input, 512).normalize('NFKC')))) {
    // ICU may split an unfamiliar name such as 星桥 into two one-character words.
    if (part.isWordLike && /^\p{Script=Han}$/u.test(part.segment) && !recallStopWords.has(part.segment)) { singleHan += part.segment; continue; }
    flush(); if (part.isWordLike) add(part.segment);
  }
  flush(); return terms.slice(0, 12);
}
