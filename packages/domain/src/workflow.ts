import { isDeepStrictEqual } from 'node:util';
import { WorkflowDefinitionSchema, JsonRecordSchema, type WorkflowDefinition } from '@lobuddy/contracts';
type Value = ReturnType<typeof JsonRecordSchema.parse>[string];
export type WorkflowValues = Record<string,Value>;
export function workflowLookup(values: WorkflowValues, reference: string): Value {
  let value: Value = values;
  for (const part of reference.split('.')) {
    if (!value || typeof value !== 'object' || Array.isArray(value) || !Object.hasOwn(value,part)) throw Error('工作流引用不存在');
    value = value[part]!;
  }
  return value;
}
export async function executeWorkflow(input: WorkflowDefinition, inputs: WorkflowValues, options: {
  active: () => boolean; signal: AbortSignal;
  tool: (name: string,args: WorkflowValues) => Promise<string>; model: (prompt: string) => Promise<string>;
  verify: () => Value; initial?: WorkflowValues; checkpoint?: (values: WorkflowValues) => void;
}): Promise<Value> {
  const definition = WorkflowDefinitionSchema.parse(input), values: WorkflowValues = { input: JsonRecordSchema.parse(inputs) };
  if (options.initial) {
    if (!isDeepStrictEqual(options.initial.input,inputs)) throw Error('检查点输入已改变');
    const completed = Object.keys(options.initial).filter(key => key !== 'input');
    const prefix = definition.nodes.slice(0,completed.length);
    if (completed.length !== prefix.length || prefix.some(node => !completed.includes(node.id) || ['model','output'].includes(node.kind) || node.tool === 'lobuddy_organize')) throw Error('检查点只能包含连续完成的只读步骤');
    Object.assign(values,JsonRecordSchema.parse(options.initial));
  }
  const check = () => { options.signal.throwIfAborted(); if (!options.active()) throw Error('工作流执行权已失效'); };
  for (const node of definition.nodes) {
    check(); if (Object.hasOwn(values,node.id)) continue;
    if (node.when && workflowLookup(values,node.when) !== true) { values[node.id] = null; continue; }
    const value = workflowLookup(values,node.source);
    if (node.kind === 'context') values[node.id] = JSON.stringify(value,null,node.format === 'pretty' ? 2 : undefined);
    else if (node.kind === 'condition') values[node.id] = node.operator === 'exists' ? value !== null : isDeepStrictEqual(value,node.expected);
    else if (node.kind === 'model') {
      const prompt = node.prompt + '\n' + JSON.stringify(value); if (Buffer.byteLength(prompt) > 7000) throw Error('工作流模型输入超过上限');
      for (let attempt = 0; attempt <= definition.repairs; attempt++) {
        check(); try { values[node.id] = await options.model(prompt); break; }
        catch (error) { check(); if (attempt === definition.repairs) throw error; }
      }
    } else if (node.kind === 'tool') {
      const args = Object.fromEntries(Object.entries(node.arguments).map(([key,value]) => [key,typeof value === 'string' && value.startsWith('$') ? workflowLookup(values,value.slice(1)) : value]));
      const result = await options.tool(node.tool!,args); check();
      try { values[node.id] = JSON.parse(result) as Value; } catch { values[node.id] = result; }
    } else if (node.kind === 'verify') values[node.id] = options.verify();
    else if (node.kind === 'output') return value;
    check(); options.checkpoint?.(values);
  }
  throw Error('工作流没有结果');
}
