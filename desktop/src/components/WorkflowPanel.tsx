import { useEffect, useState } from 'react';
import type { WorkflowView } from '../../../shared/desktop-protocol';
import { errorText, request } from '../api';
const names: Record<string,string> = {'assistant-context':'对话上下文','organize-files':'文件分类副本','source-digest':'资料归纳'};
export function WorkflowPanel() {
  const [versions,setVersions]=useState<WorkflowView[]>([]);
  const [error,setError]=useState(''),[notice,setNotice]=useState(''),[busy,setBusy]=useState(false);
  const [source,setSource]=useState(''),[output,setOutput]=useState(''),[sources,setSources]=useState('');
  const refresh=async()=>setVersions(await request('workflow.list',{}));
  useEffect(()=>{let alive=true; void request('workflow.list',{}).then(v=>{if(alive)setVersions(v);}).catch(e=>{if(alive)setError(errorText(e));});return()=>{alive=false;};},[]);
  const action=async(work:()=>Promise<unknown>)=>{setBusy(true);setError('');try{await work();await refresh();}catch(e){setError(errorText(e));}finally{setBusy(false);}};
  const run=async(id:string)=>{const session=await request('session.create',{title:names[id]||id});if(!session.id)throw Error('会话创建失败');await request('turn.send',{session_id:session.id,text:id==='organize-files'?`整理 ${source} 的副本到 ${output}`:`归纳来源：${sources}`,lane:'background',workflow_id:id,workflow_input:id==='organize-files'?{source,output}:{sources:sources.split('\n').map(v=>v.trim()).filter(Boolean)}});setNotice('已创建后台任务；请在任务页查看结果，文件复制仍需审批。');};
  return <section className="knowledge-card" aria-label="工作流与进化"><h3>工作方式与进化记录</h3><p>候选通过固定对照后才自动启用，先观察五次适用运行。启用不会自动派发任务。</p>{error&&<p role="alert">{error}</p>}{notice&&<p role="status">{notice}</p>}
    <details><summary>运行受控办事场景</summary><p>路径在设置的工作区内；文件整理只复制本层文件，资料支持 UTF-8 文件或公开链接。</p><label>输入目录<input aria-label="整理输入目录" value={source} onChange={e=>setSource(e.target.value)}/></label><label>输出目录<input aria-label="整理输出目录" value={output} onChange={e=>setOutput(e.target.value)}/></label><button disabled={busy||!source||!output} onClick={()=>void action(()=>run('organize-files'))}>预览分类副本</button><label>资料来源（每行一个）<textarea aria-label="资料来源" value={sources} onChange={e=>setSources(e.target.value)}/></label><button disabled={busy||!sources} onClick={()=>void action(()=>run('source-digest'))}>归纳这些资料</button></details>
    {versions.map(v=><details key={v.version_id}><summary>{names[v.definition.name]||v.definition.name} · {v.status} {v.active?'· 当前使用':''}</summary><p>{v.reason}</p><small>版本 {v.version_id} · 观察 {v.observed}/5 · 来源 {v.evidence.join(', ')||'内置基线'}</small><h4>改了什么</h4><pre>{v.diff}</pre><h4>固定评测结果</h4><pre>{JSON.stringify(v.evaluation,null,2)}</pre>{v.status==='candidate'&&<button disabled={busy} onClick={()=>void action(()=>request('workflow.evaluate',{version_id:v.version_id}))}>对照评测</button>}{v.active&&<button disabled={busy} onClick={()=>void action(()=>request('workflow.disable',{version_id:v.version_id}))}>停用此工作流</button>}{!v.active&&['stable','probation'].includes(v.status)&&<button disabled={busy} onClick={()=>void action(()=>request('workflow.enable',{version_id:v.version_id}))}>恢复启用</button>}{v.active&&v.parent_id&&<button disabled={busy} onClick={()=>void action(()=>request('workflow.rollback',{version_id:v.version_id}))}>否定这次改变并回退</button>}</details>)}
  </section>;
}
