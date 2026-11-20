import { closeSync, existsSync, fsyncSync, mkdirSync, openSync, readFileSync, renameSync, unlinkSync, writeFileSync } from 'node:fs';
import { dirname } from 'node:path';
import { z } from 'zod';

const usageSchema = z.strictObject({ day: z.string().regex(/^\d{4}-\d{2}-\d{2}$/u),calls: z.number().int().safe().nonnegative(),input: z.number().int().safe().nonnegative(),output: z.number().int().safe().nonnegative() });
/** Read-only admission hint; reserveEvaluation still owns the atomic check before each real request. */
export function evaluationAvailable(path: string, input: number, output: number, calls = 1): boolean {
  try {
    const day = new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Shanghai'}).format(new Date());
    const prior = existsSync(path) ? usageSchema.parse(JSON.parse(readFileSync(path,'utf8'))) : {day,calls:0,input:0,output:0};
    if (prior.day > day) return false;
    const usage = prior.day === day ? prior : {day,calls:0,input:0,output:0};
    return usage.calls + calls <= 40 && usage.input + input <= 160000 && usage.output + output <= 20000;
  } catch { return false; }
}
/** All synthetic model probes share this durable, private ledger; rebuilding fixtures never resets it. */
export function reserveEvaluation(path: string, input: number, output: number): void {
  mkdirSync(dirname(path),{ recursive: true,mode: 0o700 });
  const lock = path + '.lock', fd = openSync(lock,'wx',0o600);
  try {
    const day = new Intl.DateTimeFormat('en-CA',{ timeZone: 'Asia/Shanghai' }).format(new Date());
    const prior = existsSync(path) ? usageSchema.parse(JSON.parse(readFileSync(path,'utf8'))) : { day,calls: 0,input: 0,output: 0 };
    if (prior.day > day) throw Error('evaluation_budget_clock');
    const usage = prior.day === day ? prior : { day,calls: 0,input: 0,output: 0 };
    if (usage.calls + 1 > 40 || usage.input + input > 160000 || usage.output + output > 20000) throw Error('evaluation_budget_exhausted');
    const next = usageSchema.parse({ day,calls: usage.calls + 1,input: usage.input + input,output: usage.output + output });
    const temporary = path + '.next', target = openSync(temporary,'w',0o600);
    try { writeFileSync(target,JSON.stringify(next) + '\n'); fsyncSync(target); } finally { closeSync(target); }
    renameSync(temporary,path);
  } finally { closeSync(fd); unlinkSync(lock); }
}
