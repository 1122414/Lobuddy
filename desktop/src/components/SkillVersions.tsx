import { useEffect, useState } from 'react';
import type { ResultsByMethod } from '../../../shared/desktop-api';
import { errorText, request } from '../api';
export function SkillVersions({ id, version }: { id: string; version: number }) {
  const [rows, setRows] = useState<ResultsByMethod['skill.versions']>([]);
  const [error, setError] = useState('');
  useEffect(() => { let alive=true; void request('skill.versions', {skill_id:id}).then(value => {if (alive) setRows(value);}).catch(reason => {if (alive) setError(errorText(reason));}); return () => {alive=false;}; }, [id, version]);
  return <details><summary>完整内容版本</summary>{error && <p role="alert">{error}</p>}<p>仅保留可恢复版本，不补造旧内容。</p>{rows.map(row => <details key={row.version}><summary>v{row.version} · {row.source}</summary><pre>{row.content}</pre></details>)}</details>;
}
