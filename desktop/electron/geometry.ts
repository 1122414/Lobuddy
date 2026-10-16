export interface Rect { x: number; y: number; width: number; height: number }
export function clampWindow(bounds: Rect, displays: Rect[]): Rect {
  if (!displays.length) throw Error('No display');
  const center = { x: bounds.x + bounds.width / 2, y: bounds.y + bounds.height / 2 };
  const distance = (r: Rect) => Math.max(r.x - center.x, 0, center.x - r.x - r.width) ** 2 + Math.max(r.y - center.y, 0, center.y - r.y - r.height) ** 2;
  const area = displays.reduce((best, item) => distance(item) < distance(best) ? item : best);
  const width = Math.min(bounds.width, area.width), height = Math.min(bounds.height, area.height);
  return { width, height, x: Math.round(Math.max(area.x, Math.min(bounds.x, area.x + area.width - width))), y: Math.round(Math.max(area.y, Math.min(bounds.y, area.y + area.height - height))) };
}
export function chatBounds(pet: Rect, displays: Rect[]): Rect {
  const right = { x: pet.x + pet.width - 16, y: pet.y + pet.height - 490, width: 390, height: 490 };
  const fitted = clampWindow(right, displays);
  return fitted.x === right.x ? fitted : clampWindow({ ...right, x: pet.x - 390 + 16 }, displays);
}
