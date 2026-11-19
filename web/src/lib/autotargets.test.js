import { describe, expect, it } from 'vitest';
import { autoTargets, mergeTargets, missing, restingBurn } from './autotargets.js';

const ME = {
  sex: 'male',
  birth_year: 1996,
  height_cm: 178,
  weight_kg: 72,
  activity: 'some',
  workout_minutes: 60,
  intensity: 'moderate',
  goal: 'maintain',
};

describe('auto food targets', () => {
  it('uses Mifflin-St Jeor for resting burn', () => {
    // 10 × 72 + 6.25 × 178 − 5 × 30 + 5 = 1,687.5
    expect(restingBurn({ sex: 'male', weight_kg: 72, height_cm: 178, age: 30 })).toBe(1687.5);
    expect(restingBurn({ sex: 'female', weight_kg: 60, height_cm: 165, age: 30 })).toBeCloseTo(1320.25);
  });

  it('works out both day types with the workings', () => {
    const result = autoTargets(ME, 2026);
    expect(result.workings).toMatchObject({ age: 30, resting: 1688, factor: 1.375, daily: 2320, met: 8, workout: 504 });
    // Rest: 2,320 kcal; protein 1.6 × 72 = 115 g; fat 25% = 64 → 65 g; carbs the rest.
    expect(result.rest).toMatchObject({ kcal: 2320, protein: 115, fat: 65 });
    expect(result.rest.carbs).toBe(Math.round((2320 - 115 * 4 - 65 * 9) / 4 / 5) * 5);
    // Training adds (8 − 1) × 72 kg × 1 h = 504 kcal.
    expect(result.training.kcal).toBe(2820);
    expect(result.training.carbs).toBeGreaterThan(result.rest.carbs);
    expect(result.training.protein).toBe(result.rest.protein);
  });

  it('eats less to lose, with more protein to keep muscle', () => {
    const result = autoTargets({ ...ME, goal: 'lose' }, 2026);
    expect(result.rest.kcal).toBe(2320 - 500);
    expect(result.workings.proteinPerKg).toBe(2.0);
    expect(result.rest.protein).toBe(145);
    expect(autoTargets({ ...ME, goal: 'lose', protein_per_kg: 1.8 }, 2026).rest.protein).toBe(130);
  });

  it('never goes below resting burn', () => {
    const small = { ...ME, sex: 'female', weight_kg: 45, height_cm: 150, activity: 'sitting', goal: 'lose' };
    const result = autoTargets(small, 2026);
    expect(result.rest.kcal).toBe(Math.round(result.workings.resting / 10) * 10);
    expect(result.rest.floored).toBe(true);
  });

  it('waits for every detail', () => {
    expect(autoTargets({ ...ME, weight_kg: undefined })).toBeNull();
    expect(missing({ sex: 'male' })).toContain('weight_kg');
    expect(missing(ME)).toEqual([]);
    expect(missing({ ...ME, workout_minutes: 0 })).toEqual([]);
  });

  it('replaces the four and keeps other targets', () => {
    expect(mergeTargets({ kcal: 2000, sodium: 2300 }, { kcal: 2500, protein: 120, carbs: 300, fat: 70, burn: 1 })).toEqual({
      kcal: 2500,
      protein: 120,
      carbs: 300,
      fat: 70,
      sodium: 2300,
    });
  });
});
