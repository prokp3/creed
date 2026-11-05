import { describe, expect, it } from 'vitest';
import { motionBetween } from './motion.js';

describe('motionBetween', () => {
  it('fades between tabs', () => {
    expect(motionBetween('today', 'in-depth')).toBe('tab');
    expect(motionBetween('activities', 'today')).toBe('tab');
  });

  it('slides in when going deeper', () => {
    expect(motionBetween('today', 'settings')).toBe('push');
    expect(motionBetween('activities', 'activity')).toBe('push');
    expect(motionBetween('activity', 'activity-map')).toBe('push');
  });

  it('slides back when coming out', () => {
    expect(motionBetween('settings', 'today')).toBe('pop');
    expect(motionBetween('activity-map', 'activity')).toBe('pop');
    expect(motionBetween('activity', 'activities')).toBe('pop');
  });

  it('does nothing when the screen stays the same', () => {
    expect(motionBetween('activity', 'activity')).toBeNull();
  });
});
