import { PetStateSchema, PetProgressEventSchema, localTimestamp, type PetState, type AbilityView } from '@lobuddy/contracts';
const EXP = [50, 120, 220, 350, 520, 720, 950, 1220, 1550];
export const requiredExp = (level: number): number => {
  if (!Number.isInteger(level) || level < 1 || level > 10) throw Error('等级无效');
  return EXP[level - 1] ?? 9999;
};
export function difficulty(text: string): { difficulty: 'simple' | 'medium' | 'complex'; reward: number } {
  text = text.trim().toLowerCase();
  const complex = ['代码','code','程序','program','脚本','script','分析','analyze','分析','analysis','优化','optimize','重构','refactor','设计','design','架构','architecture','实现','implement','开发','develop','比较','compare','对比','versus','vs','解释','explain','详细','detail'].filter(word => text.includes(word)).length;
  const medium = ['搜索','search','查找','find','总结','summarize','概括','summary','转换','convert','翻译','translate','修复','fix','调试','debug','创建','create','生成','generate','写','write','撰写','compose'].filter(word => text.includes(word)).length;
  const length = [...text].length;
  if (length > 200 || complex >= 2 || (complex >= 1 && length > 100)) return { difficulty: 'complex', reward: 30 };
  if (length > 80 || medium >= 1 || complex === 1) return { difficulty: 'medium', reward: 15 };
  return { difficulty: 'simple', reward: 5 };
}
type Trait = 'technical_skill' | 'curiosity' | 'creativity' | 'diligence' | 'friendliness';
const PATTERNS: Partial<Record<Trait, string[]>> = {
  technical_skill: ['code|program|debug|error|function|class|import|api', 'python|javascript|java|rust|go|sql|git|github',
    'algorithm|database|server|backend|frontend|framework', 'bug|fix|refactor|deploy|build|compile'],
  curiosity: ['how|why|what|explain|learn|understand|teach', 'different|alternative|compare|vs|versus|difference',
    'explore|discover|research|investigate|curious'],
  creativity: ['create|design|build|make|generate|imagine', 'story|art|music|game|app|project|idea', 'improve|enhance|optimize|innovate|creative'],
};
export function addExperience(value: PetState, amount: number): boolean {
  if (!Number.isSafeInteger(amount) || amount < 0 || !Number.isSafeInteger(value.exp + amount)) throw Error('经验值无效');
  value.exp += amount; value.updated_at = localTimestamp(); let changed = false;
  while (value.level < 10 && value.exp >= requiredExp(value.level)) {
    value.exp -= requiredExp(value.level); value.level++;
    value.evolution_stage = Math.min(Math.floor(value.level / 4) + 1, 3) as 1 | 2 | 3; changed = true;
  }
  return changed;
}
export function rewardCompletion(value: PetState, text: string) {
  const pet = PetStateSchema.parse(value), task = difficulty(text);
  const progress = PetProgressEventSchema.parse({ exp_gained: task.reward });
  progress.level_up = addExperience(pet, task.reward);
  if (progress.level_up) { progress.new_level = pet.level; progress.new_stage = pet.evolution_stage; }
  const adjustments: Partial<Record<Trait, number>> = { diligence: 0.3 };
  for (const [trait, patterns] of Object.entries(PATTERNS)) {
    // Python's word boundaries include Unicode letters and digits, unlike JS \b.
    const score = patterns.filter(words => new RegExp(`(?<![\\p{L}\\p{N}_])(${words})(?![\\p{L}\\p{N}_])`, 'iu').test(text)).length;
    if (score) adjustments[trait as Trait] = Math.min(2, score * 0.5 * ({ simple: 0.5, medium: 1, complex: 1.5 }[task.difficulty]));
  }
  for (const [name, delta] of Object.entries(adjustments)) {
    const trait = name as Trait; pet.personality[trait] = Math.min(100, Math.max(0, pet.personality[trait] + delta));
    const key = `${trait}:task_analysis`;
    pet.personality.interaction_counts[key] = (pet.personality.interaction_counts[key] ?? 0) + 1;
  }
  progress.personality_adjustments = adjustments;
  progress.current_exp = pet.exp; progress.required_exp = requiredExp(pet.level);
  return { pet, progress };
}
const ability = (id: string, name: string, description: string, type: string, requirements: Partial<AbilityView>): AbilityView => ({
  id, name, description, type, min_level: null, min_stage: null, trait: null, trait_value: null, tasks_completed: null, unlocked_at: null, ...requirements,
});
export const ABILITIES = [
  ability('advanced_chat', 'Advanced Chat', 'Can maintain longer and more complex conversations', 'functional', { min_level: 3 }),
  ability('multi_task', 'Multi-Tasking', 'Can handle multiple tasks simultaneously', 'functional', { min_level: 5 }),
  ability('code_assist', 'Code Assistant', 'Enhanced code generation and debugging capabilities', 'tool', { min_level: 4, trait: 'technical_skill', trait_value: 60 }),
  ability('creative_mode', 'Creative Mode', 'Can help with creative writing and design tasks', 'tool', { min_level: 4, trait: 'creativity', trait_value: 65 }),
  ability('social_butterfly', 'Social Butterfly', 'Pet becomes more expressive and socially engaging', 'social', { min_level: 6, trait: 'friendliness', trait_value: 70 }),
  ability('evolution_stage2', 'Growth Evolution', 'Pet evolves to growth stage with new appearance', 'cosmetic', { min_stage: 2 }),
  ability('evolution_stage3', 'Final Evolution', 'Pet reaches final form', 'cosmetic', { min_stage: 3 }),
];
export function availableAbilities(pet: PetState, count: number): AbilityView[] {
  return ABILITIES.filter(rule => (!rule.min_level || pet.level >= rule.min_level) && (!rule.min_stage || pet.evolution_stage >= rule.min_stage) &&
    (!rule.tasks_completed || count >= rule.tasks_completed) && (!rule.trait || pet.personality[rule.trait as Trait] >= (rule.trait_value ?? 0)));
}
