import { createBackup, verifyBackup, importBackup, restoreBackup } from './backup.js';
import { Store, StorageError } from './database.js';
import { resolve, join } from 'node:path';
const [command, ...args] = process.argv.slice(2);
try {
  let result: unknown;
  if (command === 'init' && args.length === 1) {
    const store = new Store(join(resolve(args[0]!), 'lobuddy.db'), { create: true });
    store.close(); result = { created: true, storage_version: 3 };
  } else if (command === 'backup' && args.length === 3) {
    const manifest = await createBackup(args[0]!, args[1]!, args[2]!);
    result = { identity: manifest.identity, files: Object.keys(manifest.files).length };
  } else if (command === 'verify' && args.length === 1) {
    const manifest = await verifyBackup(args[0]!); result = { verified: true, identity: manifest.identity };
  } else if (command === 'import' && args.length === 2) result = await importBackup(args[0]!, args[1]!);
  else if (command === 'restore' && args.length === 2) { await restoreBackup(args[0]!, args[1]!); result = { restored: true }; }
  else throw new StorageError('用法：init DATA | backup DATA WORKSPACE DEST | verify BACKUP | import BACKUP DEST | restore BACKUP DEST');
  console.log(JSON.stringify(result));
} catch (error) {
  // SQLite/Zod errors can contain user values. Only deliberate storage diagnostics leave this CLI.
  console.error(error instanceof StorageError ? error.message : '资料操作失败；原资料未被覆盖。请检查格式、权限与版本。');
  process.exitCode = 1;
}
