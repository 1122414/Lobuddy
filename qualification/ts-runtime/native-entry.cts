import { isAbsolute } from 'node:path';
import { writeFileSync } from 'node:fs';

// rc.1's dshBin is a JS entry. Replace this process, preserving PID and stdio,
// so SDK shutdown still owns the native runtime without an intermediate child.
const binary = process.env.LOBUDDY_QUALIFY_DSH;
if (!binary || !isAbsolute(binary) || !process.execve) {
  throw new Error('Native DSH requires an absolute binary path and POSIX execve');
}
const environment = { ...process.env };
delete environment.ELECTRON_RUN_AS_NODE;
delete environment.NODE_OPTIONS;
const identityPath = process.env.LOBUDDY_QUALIFY_PID;
if (identityPath) writeFileSync(identityPath, String(process.pid), { mode: 0o600, flag: 'wx' });
process.execve(binary, [binary, ...process.argv.slice(2)], environment);
