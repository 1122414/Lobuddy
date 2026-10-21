const { writeFileSync } = require('node:fs');
const { resolve, join } = require('node:path');

// Isolate Chromium selection/storage as well as the business database. Keep the
// production entrypoint and app path, including its real permission handlers.
function isolatedDesktopArgs(directory) {
  const bootstrap = join(directory, 'desktop-bootstrap.cjs');
  writeFileSync(bootstrap, `const { app } = require('electron');
app.setPath('userData', ${JSON.stringify(join(directory, 'electron'))});
app.setAppPath(${JSON.stringify(resolve(__dirname, '..'))});
require(${JSON.stringify(resolve(__dirname, '../dist-electron/desktop/electron/main.js'))});
`, { mode: 0o600 });
  return [bootstrap];
}

module.exports = { isolatedDesktopArgs };
