// Auto food targets: daily calories, protein, carbs and fat for training days and rest days, from your body,
// your day and your training. Every step is returned so the screen can show its workings. These are estimates to
// start from: weigh yourself over a couple of weeks and adjust.
//
// Sources:
// - Resting burn: Mifflin-St Jeor (1990), the equation most dietitians use; within about 10% for most adults.
// - Day-to-day activity: the usual activity factors on top of resting burn (1.2 mostly sitting, 1.375 on your feet
//   some of the day, 1.55 most of the day), before any workout.
// - Workout burn: METs from the Compendium of Physical Activities (Ainsworth 2011). Easy endurance work is about 6,
//   steady 8 and hard 10. One MET is already counted in resting burn, so a workout adds (MET − 1) × kg × hours.
// - Protein: 1.6 g per kg a day for endurance athletes, 2.0 g/kg when losing weight to keep muscle (ISSN 2017,
//   ACSM 2016: 1.2 to 2.0 g/kg).
// - Fat: 25% of calories (ACSM: 20 to 35%).
// - Carbs: what's left, shown per kg so it can be compared with ACSM's 5 to 7 g/kg for about an hour a day.

export const ACTIVITY = [
  { id: 'sitting', label: 'Mostly sitting', factor: 1.2 },
  { id: 'some', label: 'On my feet some', factor: 1.375 },
  { id: 'feet', label: 'On my feet a lot', factor: 1.55 },
];

export const INTENSITY = [
  { id: 'easy', label: 'Easy', met: 6 },
  { id: 'moderate', label: 'Steady', met: 8 },
  { id: 'hard', label: 'Hard', met: 10 },
];

export const GOALS = [
  { id: 'lose', label: 'Lose weight (about 0.5 kg a week)', change: -500 },
  { id: 'lose_slowly', label: 'Lose slowly (about 0.25 kg a week)', change: -250 },
  { id: 'maintain', label: 'Stay the same', change: 0 },
  { id: 'gain_slowly', label: 'Gain slowly (about 0.25 kg a week)', change: 250 },
];

const FAT_SHARE = 0.25;
const NEEDED = ['sex', 'birth_year', 'height_cm', 'weight_kg', 'activity', 'workout_minutes', 'intensity', 'goal'];

const round = (value, step) => Math.round(value / step) * step;

/** Which details are still missing, as their field names. Empty when targets can be worked out. */
export function missing(profile) {
  return NEEDED.filter((key) => profile?.[key] === undefined || profile[key] === null || profile[key] === '');
}

/** Resting burn in kcal a day (Mifflin-St Jeor). */
export function restingBurn({ sex, weight_kg, height_cm, age }) {
  return 10 * weight_kg + 6.25 * height_cm - 5 * age + (sex === 'male' ? 5 : -161);
}

/**
 * Targets for both day types, with workings. `year` is this year, for the age. Returns null until every detail is
 * filled in.
 */
export function autoTargets(profile, year = new Date().getFullYear()) {
  if (missing(profile).length) return null;
  const weight = profile.weight_kg;
  const age = year - profile.birth_year;
  const activity = ACTIVITY.find((a) => a.id === profile.activity);
  const intensity = INTENSITY.find((i) => i.id === profile.intensity);
  const goal = GOALS.find((g) => g.id === profile.goal);
  const resting = restingBurn({ ...profile, age });
  const daily = resting * activity.factor;
  const workout = (intensity.met - 1) * weight * (profile.workout_minutes / 60);
  const proteinPerKg = profile.protein_per_kg ?? (goal.change < 0 ? 2.0 : 1.6);

  const day = (burn) => {
    // Never below resting burn: eating less than that on purpose needs a doctor, not an app.
    const wanted = burn + goal.change;
    const kcal = round(Math.max(wanted, resting), 10);
    const protein = round(proteinPerKg * weight, 5);
    const fat = round((kcal * FAT_SHARE) / 9, 5);
    const carbs = Math.max(0, round((kcal - protein * 4 - fat * 9) / 4, 5));
    return { kcal, protein, carbs, fat, burn: Math.round(burn), floored: wanted < resting, carbsPerKg: carbs / weight };
  };

  return {
    training: day(daily + workout),
    rest: day(daily),
    workings: {
      age,
      resting: Math.round(resting),
      factor: activity.factor,
      daily: Math.round(daily),
      met: intensity.met,
      workout: Math.round(workout),
      change: goal.change,
      proteinPerKg,
      fatShare: FAT_SHARE,
    },
  };
}

/** New target sets: these four replace the old ones, and any other targets (sodium and so on) are kept. */
export function mergeTargets(existing, worked) {
  const { kcal, protein, carbs, fat } = worked;
  return { ...(existing ?? {}), kcal, protein, carbs, fat };
}
