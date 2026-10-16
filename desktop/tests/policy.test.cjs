const test = require('node:test');
const assert = require('node:assert/strict');
const { assetPath, externalURL } = require('../dist-electron/desktop/electron/policy');
test('only app origin and files beneath packaged asset root are served', () => {
  assert.equal(assetPath('lobuddy://app/index.html', '/assets'), '/assets/index.html');
  assert.equal(assetPath('lobuddy://app/assets/app.js', '/assets'), '/assets/assets/app.js');
  for (const url of ['https://app/index.html', 'lobuddy://other/index.html', 'lobuddy://app/%2e%2e%2fsecret', 'lobuddy://app/a%5csecret', 'lobuddy://app/%00']) assert.throws(() => assetPath(url, '/assets'));
});
test('external navigation never accepts code, files, credentials or OS schemes', () => {
  assert.equal(externalURL('https://example.com/page'), 'https://example.com/page');
  for (const url of ['file:///etc/passwd', 'javascript:alert(1)', 'data:text/html,test', 'https://user:secret@example.com', 'x-apple.systempreferences:test', 123]) assert.throws(() => externalURL(url));
});
