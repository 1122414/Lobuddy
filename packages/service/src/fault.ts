import type { ErrorCode } from '@lobuddy/contracts';

const messages: Record<ErrorCode, string> = {
  invalid_request: '请求参数无效。', unsupported_method: '该业务能力尚不可用。',
  id_conflict: '请求 ID 与先前内容冲突。', not_ready: '业务服务尚未连接。',
  unavailable: '业务服务已断开，操作不会自动重试。', cancelled: '操作已取消。',
  timeout: '请求超时，未自动重试。请查看任务状态。', internal_error: '操作未完成，请检查服务状态。',
};
export class RpcFault extends Error {
  constructor(readonly code: ErrorCode) { super(messages[code]); this.name = 'RpcFault'; }
}
