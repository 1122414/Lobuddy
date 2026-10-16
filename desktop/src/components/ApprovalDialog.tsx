import { useEffect, useRef, useState } from 'react';
import type { Approval } from '../../../shared/desktop-api';
export function ApprovalDialog({ approval, onResolve }: { approval: Approval | undefined; onResolve: (id: string, approved: boolean) => Promise<void> }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [pending, setPending] = useState(false);
  useEffect(() => { if (approval) { if (!dialog.current?.open) dialog.current?.showModal(); } else dialog.current?.close(); }, [approval]);
  const resolve = async (approved: boolean) => {
    if (!approval || pending) return;
    setPending(true);
    try { await onResolve(approval.approval_id, approved); } finally { setPending(false); }
  };
  return <dialog ref={dialog} className="approval" aria-labelledby="approval-title" onCancel={event => { event.preventDefault(); void resolve(false).catch(() => undefined); }}>
    <h2 id="approval-title">这一步需要你确认</h2><p>{approval?.reason}</p><pre>{approval?.command}</pre><p className="quiet">仅允许本次操作。关闭窗口或超时将拒绝执行。</p><div className="dialog-actions"><button autoFocus disabled={pending} onClick={() => void resolve(false).catch(() => undefined)}>拒绝</button><button className="primary" disabled={pending} onClick={() => void resolve(true).catch(() => undefined)}>允许本次</button></div>
  </dialog>;
}
