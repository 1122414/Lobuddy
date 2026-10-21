import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, rm, writeFile, readFile, stat, symlink, readdir } from 'node:fs/promises';
import { randomBytes } from 'node:crypto';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import sharp from 'sharp';
import { ImageStore } from './tools/images.js';

test('native image admission keeps source bytes, private durable IDs and decodable previews across restart', async () => {
  const root = await mkdtemp(join(tmpdir(),'lobuddy-images-')), data = join(root,'private'), images = new ImageStore(data);
  try {
    for (const format of ['png','jpeg','webp','gif'] as const) {
      const original = await sharp({ create: { width: 60,height: 30,channels: 3,background: 'red' } }).toFormat(format).toBuffer();
      const path = join(root,`sample.${format}`); await writeFile(path,original);
      const image = await images.importFile(path);
      assert.equal(image.width,60); assert.equal(image.height,30); assert.equal(image.media_type,`image/${format}`);
      assert.match(image.preview,/^data:image\/jpeg;base64,/);
      assert.equal((await sharp(Buffer.from(image.preview.split(',')[1]!,'base64')).metadata()).width,60);
      assert.equal((await stat(join(data,image.image_id))).mode & 0o777,0o600);
      assert.deepEqual(await images.importFile(path),image);
      assert.deepEqual(await new ImageStore(data).get(image.image_id),image);
      assert.deepEqual(await readFile(path),original);
      await writeFile(join(data,image.image_id),'tampered'); await assert.rejects(images.get(image.image_id),/校验/);
    }
  } finally { await rm(root,{ recursive: true,force: true }); }
});
test('image admission rejects invalid content, extension mismatches, symlinks, unsafe references and raster bombs without publishing data', async () => {
  const root = await mkdtemp(join(tmpdir(),'lobuddy-images-invalid-')), data = join(root,'private'), images = new ImageStore(data);
  try {
    const png = await sharp({ create: { width: 10,height: 10,channels: 3,background: 'red' } }).png().toBuffer();
    for (const [name,bytes] of [ ['wrong.jpg',png], ['broken.png',Buffer.from('\x89PNG\r\n\x1a\n')],
      ['fake.png',Buffer.from('not an image')], ['malware.exe',png], ['fake.svg',Buffer.from('<?xml version="1.0"?><not-svg/>')] ] as const) {
      const path = join(root,name); await writeFile(path,bytes); await assert.rejects(images.importFile(path));
    }
    await writeFile(join(root,'valid.png'),png); await symlink(join(root,'valid.png'),join(root,'link.png'));
    await assert.rejects(images.importFile(join(root,'link.png'))); await assert.rejects(images.importFile(join(root,'missing.png')));
    for (const id of ['../valid.png','', 'a'.repeat(63),'g'.repeat(64)]) await assert.rejects(images.get(id));
    const wide = await sharp({ create: { width: 16385,height: 1,channels: 3,background: 'black' } }).png().toBuffer();
    assert.ok(wide.length < 1000); await assert.rejects(images.importBytes(wide,'.png'),/尺寸/);
    const bomb = await sharp({ create: { width: 6400,height: 6400,channels: 3,background: 'black' } }).png().toBuffer();
    await assert.rejects(images.importBytes(bomb,'.png'),/pixel limit/);
    await assert.rejects(images.importBytes(Buffer.alloc(100 * 1024 * 1024 + 1),'.png'),/大小/);
    await assert.rejects(readdir(data),{ code: 'ENOENT' });
  } finally { await rm(root,{ recursive: true,force: true }); }
});
test('oversized real rasters are compressed below the attachment limit without rewriting the original', async () => {
  const root = await mkdtemp(join(tmpdir(),'lobuddy-images-compress-')), images = new ImageStore(join(root,'private'));
  try {
    const bytes = await sharp(randomBytes(2500 * 2500 * 3), { raw: { width: 2500,height: 2500,channels: 3 } }).jpeg({ quality: 100 }).toBuffer();
    assert.ok(bytes.length > 5 * 1024 * 1024);
    const source = join(root,'large.jpg'); await writeFile(source,bytes);
    const image = await images.importFile(source), stored = await readFile(join(root,'private',image.image_id));
    assert.ok(stored.length <= 5 * 1024 * 1024); assert.equal((await sharp(stored).metadata()).format,'jpeg');
    assert.deepEqual(await readFile(source),bytes); assert.deepEqual(await images.get(image.image_id),image);
  } finally { await rm(root,{ recursive: true,force: true }); }
});
