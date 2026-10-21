import sharp from 'sharp';
import { isAbsolute, join, extname, resolve, sep } from 'node:path';
import { realpath } from 'node:fs/promises';
import { CompanionPreferencesSchema, JsonRecordSchema, type CompanionPreferences } from '@lobuddy/contracts';
import { Preferences } from '../storage/preferences.js';
import { Store } from '../storage/database.js';
import { readPrivate } from '../storage/files.js';
import { ImageStore } from '../tools/images.js';
export class CompanionAppearance {
  readonly images: ImageStore;
  readonly preferences: Preferences;
  value: CompanionPreferences;
  constructor(store: Store, readonly data: string) {
    this.preferences = new Preferences(store); this.images = new ImageStore(join(data,'pet-images'));
    this.value = CompanionPreferencesSchema.parse(this.preferences.json('desktop_companion'));
  }
  async initialize(): Promise<void> {
    if (this.preferences.get('desktop_companion') !== undefined) return;
    try {
      const legacy = JsonRecordSchema.parse(JSON.parse((await readPrivate(join(this.data,'pet_appearance.json'))).toString('utf8')));
      this.value = CompanionPreferencesSchema.parse(Object.fromEntries(['scale','opacity','always_on_top'].filter(key => key in legacy).map(key => [key,legacy[key]])));
      const custom = legacy.custom_asset_path;
      if (typeof custom === 'string' && custom) {
        const base = await realpath(this.data), source = await realpath(resolve(this.data,custom));
        if (!source.startsWith(base + sep)) throw Error('旧外观需要重新选择');
        await this.importImage(source);
      }
      await this.save(this.value);
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== 'ENOENT') process.stderr.write('旧外观未能完整迁移，保留来源；可重新选择图片。\n');
    }
  }
  async save(input: CompanionPreferences): Promise<CompanionPreferences> {
    const value = CompanionPreferencesSchema.parse(input);
    if (value.sprite === 'custom') {
      if (!value.image_id) throw Error('请先选择宠物图片'); await this.images.get(value.image_id);
    }
    this.preferences.set('desktop_companion',JSON.stringify(value)); this.value = value; return value;
  }
  async importImage(path: string): Promise<CompanionPreferences> {
    if (!isAbsolute(path)) throw Error('请选择本地图片');
    const data = await readPrivate(path,5 * 1024 * 1024);
    const info = await sharp(data,{ animated: true, limitInputPixels: 80_000_000, failOn: 'warning' }).metadata();
    const frames = info.pages ?? 1, height = info.pageHeight ?? info.height ?? 0;
    if (!info.width || !height || frames > 300 || info.width * height * frames > 80_000_000) throw Error('宠物动画帧数或总尺寸超过限制');
    // Force decoding of all frames; metadata alone does not validate truncated animations.
    await sharp(data,{ animated: true, limitInputPixels: 80_000_000, failOn: 'warning' }).stats();
    const image = await this.images.importBytes(data,extname(path).toLowerCase());
    return this.save({ ...this.value, sprite: 'custom', image_id: image.image_id });
  }
}
