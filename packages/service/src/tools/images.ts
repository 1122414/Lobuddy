import sharp from 'sharp';
import { createHash } from 'node:crypto';
import { mkdir, lstat, chmod } from 'node:fs/promises';
import { extname, isAbsolute, join } from 'node:path';
import { ImageInfoSchema, ImageReferenceSchema } from '@lobuddy/contracts';
import { atomicPrivateWrite, readPrivate } from '../storage/files.js';
const FORMATS: Record<string, string> = { png: 'image/png', jpeg: 'image/jpeg', gif: 'image/gif', webp: 'image/webp' };
const EXTENSIONS: Record<string, string> = { '.png': 'png', '.jpg': 'jpeg', '.jpeg': 'jpeg', '.gif': 'gif', '.webp': 'webp' };
const MAX_BYTES = 5 * 1024 * 1024;
export class ImageStore {
  constructor(private readonly root: string) {}
  private async decode(data: Buffer) {
    const image = sharp(data, { limitInputPixels: 40_000_000, failOn: 'warning' });
    const info = await image.metadata();
    if (!info.format || !FORMATS[info.format] || !info.width || !info.height || Math.max(info.width, info.height) > 16384 || info.width * info.height > 40_000_000) throw Error('图片实际格式或尺寸不符合限制');
    const preview = await image.resize(320, 320, { fit: 'inside', withoutEnlargement: true }).flatten({ background: '#000' }).jpeg({ quality: 75 }).toBuffer();
    return { format: info.format, width: info.width, height: info.height, preview: 'data:image/jpeg;base64,' + preview.toString('base64') };
  }
  async importFile(path: string) {
    const extension = extname(path).toLowerCase(); if (!isAbsolute(path) || !EXTENSIONS[extension]) throw Error('请选择支持的本地图片');
    return this.importBytes(await readPrivate(path, 100 * 1024 * 1024), extension);
  }
  async importBytes(input: Buffer, extension: string) {
    if (!input.length || input.length > 100 * 1024 * 1024) throw Error('图片大小不符合限制');
    const info = await this.decode(input); if (EXTENSIONS[extension] !== info.format) throw Error('图片扩展名与实际格式不一致');
    let data = input;
    if (data.length > MAX_BYTES) {
      for (const quality of [85,75,65,55,45,35]) {
        data = await sharp(input, { limitInputPixels: 40_000_000 }).flatten({ background: '#000' }).jpeg({ quality, mozjpeg: true }).toBuffer();
        if (data.length <= MAX_BYTES) break;
      }
      if (data.length > MAX_BYTES) for (const scale of [0.8,0.7,0.6,0.5,0.4,0.3]) {
        data = await sharp(input, { limitInputPixels: 40_000_000 }).resize(Math.floor(info.width * scale), Math.floor(info.height * scale))
          .flatten({ background: '#000' }).jpeg({ quality: 70, mozjpeg: true }).toBuffer();
        if (data.length <= MAX_BYTES) break;
      }
    }
    if (data.length > MAX_BYTES) throw Error('压缩后图片仍超过 5 MB'); await this.decode(data);
    await mkdir(this.root, { recursive: true, mode: 0o700 });
    if ((await lstat(this.root)).isSymbolicLink()) throw Error('图片目录不能为符号链接'); await chmod(this.root, 0o700);
    const id = createHash('sha256').update(data).digest('hex');
    await atomicPrivateWrite(join(this.root, id), data); return this.get(id);
  }
  async get(id: string) {
    ImageReferenceSchema.parse({ image_id: id });
    const data = await readPrivate(join(this.root, id), MAX_BYTES);
    if (createHash('sha256').update(data).digest('hex') !== id) throw Error('图片校验失败，请重新选择');
    const { format, ...info } = await this.decode(data);
    return ImageInfoSchema.parse({ image_id: id, media_type: FORMATS[format], ...info });
  }
}
