import { isAbsolute } from 'node:path';
import { writeFileSync } from 'node:fs';

// The pinned SDK launches a JS entry; execve transfers its PID/stdio to the native runtime.
const binary = process.env.LOBUDDY_DSH_BINARY;
const identity = process.env.LOBUDDY_DSH_PID_FILE;
if (!binary || !identity || !isAbsolute(binary) || !isAbsolute(identity) || !process.execve) {
  throw new Error('DSH native launch configuration is unavailable');
}
const environment = { ...process.env };
delete environment.ELECTRON_RUN_AS_NODE;
delete environment.NODE_OPTIONS;
writeFileSync(identity, String(process.pid), { mode: 0o600, flag: 'wx' });
process.execve(binary, [binary, ...process.argv.slice(2)], environment);
