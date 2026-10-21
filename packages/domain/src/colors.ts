export const rgb = (hex: string) => [1,3,5].map(offset => Number.parseInt(hex.slice(offset,offset + 2),16)) as [number,number,number];
const hex = (values: number[]) => '#' + values.map(n => Math.trunc(n).toString(16).padStart(2,'0')).join('');
export function contrastRatio(a: string, b: string): number {
  const luminance = (color: string) => rgb(color).map(n => { const c = n / 255; return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4; })
    .reduce((total,n,i) => total + n * [0.2126,0.7152,0.0722][i]!,0);
  const first = luminance(a), second = luminance(b); return (Math.max(first,second) + 0.05) / (Math.min(first,second) + 0.05);
}
export function shiftLightness(color: string, amount: number): string {
  const [r,g,b] = rgb(color).map(n => n / 255) as [number,number,number];
  const max = Math.max(r,g,b), min = Math.min(r,g,b), old = (max + min) / 2;
  const light = Math.min(1,Math.max(0,old + amount)); if (max === min) return hex([light * 255,light * 255,light * 255]);
  const d = max - min, saturation = old <= 0.5 ? d / (max + min) : d / (2 - max - min);
  let h = max === r ? (g - b) / d : max === g ? 2 + (b - r) / d : 4 + (r - g) / d;
  h = ((h / 6) % 1 + 1) % 1;
  const m2 = light <= 0.5 ? light * (1 + saturation) : light + saturation - light * saturation, m1 = 2 * light - m2;
  const channel = (offset: number) => { const hue = ((h + offset) % 1 + 1) % 1;
    return (hue < 1 / 6 ? m1 + (m2 - m1) * hue * 6 : hue < 0.5 ? m2 : hue < 2 / 3 ? m1 + (m2 - m1) * (2 / 3 - hue) * 6 : m1) * 255; };
  return hex([channel(1 / 3),channel(0),channel(-1 / 3)]);
}
