import sharp from 'sharp';
import { randomUUID } from 'node:crypto';
import { join } from 'node:path';
import { ThemeSaveSchema, ThemeViewSchema, JsonRecordSchema, localTimestamp, type ThemeSave, type ThemeView } from '@lobuddy/contracts';
import { contrastRatio, shiftLightness } from '@lobuddy/domain';
import { Store } from '../storage/database.js';
import { readPrivate } from '../storage/files.js';
import { ImageStore } from '../tools/images.js';
import { CompanionAppearance } from './appearance.js';
import { parseStoredJson } from '../storage/json.js';
export class ThemeService {
  constructor(readonly store: Store, readonly appearance: CompanionAppearance, readonly images: ImageStore, readonly imageRoot: string) {}
  list(): ThemeView[] {
    return this.store.connection.prepare('SELECT * FROM user_themes ORDER BY updated_at DESC LIMIT 50').all().map(row => {
      const colors = JsonRecordSchema.parse(parseStoredJson(String(row.colors_json)));
      return ThemeViewSchema.parse({ theme_id: row.id, name: row.name, accent: colors.primary ?? '#367572', side: colors.side ?? colors.primary_soft ?? '#deebec' });
    });
  }
  save(input: ThemeSave): ThemeView {
    const value = ThemeSaveSchema.parse(input), id = randomUUID(), now = localTimestamp();
    this.store.run('INSERT INTO user_themes VALUES(?,?,?, ?,NULL,0,?,?)', id,value.name,'manual',JSON.stringify({ primary: value.accent, side: value.side }),now,now);
    return { ...value, theme_id: id };
  }
  async apply(id: string): Promise<void> {
    const selected = this.list().find(value => value.theme_id === id); if (!selected) throw Error('主题不存在');
    await this.appearance.save({ ...this.appearance.value, accent: selected.accent, side: selected.side });
    this.store.transaction(() => { this.store.run('UPDATE user_themes SET is_active=0'); this.store.run('UPDATE user_themes SET is_active=1 WHERE id=?',id); });
  }
  remove(id: string): boolean { return this.store.run('DELETE FROM user_themes WHERE id=?',id).changes > 0; }
  async fromImage(id: string): Promise<ThemeSave> {
    await this.images.get(id); const bytes = await readPrivate(join(this.imageRoot,id),5 * 1024 * 1024);
    const reduced = await sharp(bytes,{ limitInputPixels: 40_000_000, failOn: 'warning' }).resize(100,100,{ fit: 'inside', withoutEnlargement: true })
      .removeAlpha().png({ palette: true, colours: 8 }).toBuffer();
    const raw = await sharp(reduced).removeAlpha().toColourspace('srgb').raw().toBuffer();
    const counts = new Map<string, { count: number; rgb: number[] }>();
    for (let i = 0; i < raw.length; i += 3) {
      const values = [raw[i]!,raw[i + 1]!,raw[i + 2]!], key = values.join(',');
      counts.set(key,{ count: (counts.get(key)?.count ?? 0) + 1, rgb: values });
    }
    const values = [...counts.values()].sort((a,b) => b.count - a.count).find(item => Math.max(...item.rgb) - Math.min(...item.rgb) > 30)?.rgb ?? [54,117,114];
    let accent = '#' + values.map(n => n.toString(16).padStart(2,'0')).join(''); const side = shiftLightness(accent,0.85);
    for (let i = 0; i < 20 && contrastRatio(accent,'#ffffff') < 4.5; i++) accent = shiftLightness(accent,-0.1);
    return ThemeSaveSchema.parse({ name: '图片配色', accent, side });
  }
}
