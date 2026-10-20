const { test } = require('node:test');
const assert = require('node:assert/strict');
const { clampWindow, chatBounds } = require('../dist-electron/desktop/electron/geometry');
test('window remains visible on negative-coordinate and removed displays in DIP', () => {
  const areas = [{ x: -1920, y: 0, width: 1920, height: 1080 }, { x: 0, y: 24, width: 1512, height: 900 }];
  const left = { x: -1600, y: 500, width: 300, height: 400 };
  assert.deepEqual(clampWindow(left, areas), left);
  assert.deepEqual(clampWindow(left, [areas[1]]), { x: 0, y: 500, width: 300, height: 400 });
  assert.deepEqual(clampWindow({ x: 1500, y: 900, width: 300, height: 500 }, areas), { x: 1212, y: 424, width: 300, height: 500 });
  assert.deepEqual(clampWindow({ x: 0, y: 0, width: 3000, height: 2000 }, [areas[1]]), areas[1]);
  const chat = chatBounds({ x: 1252, y: 624, width: 260, height: 300 }, areas);
  assert.equal(chat.x, 878); assert.equal(chat.y, 434);
});
