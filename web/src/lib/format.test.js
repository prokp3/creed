import { describe, expect, it } from 'vitest';
import {
  clock,
  countdownParts,
  dayHeading,
  distance,
  duration,
  localClock,
  longDate,
  pace,
  relativeDay,
  restingDifference,
  shortDate,
  signed,
  to12Hour,
  to24Hour,
  whole,
  zonedClock,
  zonedDate,
} from './format.js';

describe('durations', () => {
  it('shows seconds as a clock', () => {
    expect(clock(20880)).toBe('5:48');
    expect(clock(27900)).toBe('7:45');
    expect(clock(300)).toBe('0:05');
    expect(clock(null)).toBe('—');
  });

  it('shows seconds in words', () => {
    expect(duration(20880)).toBe('5h 48m');
    expect(duration(3300)).toBe('55m');
    expect(duration(3660)).toBe('1h 01m');
    expect(duration(undefined)).toBe('—');
  });
});

describe('distance', () => {
  it('uses metres for swims', () => {
    expect(distance('swim', 1800)).toBe('1,800 m');
  });

  it('uses kilometres for everything else', () => {
    expect(distance('run', 10200)).toBe('10.2 km');
    expect(distance('bike', 24000)).toBe('24 km');
  });

  it('shows no value rather than zero when missing', () => {
    expect(distance('run', null)).toBe('—');
  });
});

describe('pace', () => {
  it('shows running pace per kilometre', () => {
    // 1000 m at 2.924 m/s takes 342 s, which is 5:42.
    expect(pace('run', 1000 / 342)).toBe('5:42 /km');
  });

  it('shows swim pace per 100 m', () => {
    // 100 m at 0.8 m/s takes 125 s, which is 2:05.
    expect(pace('swim', 0.8)).toBe('2:05 /100 m');
  });

  it('shows bike speed in km/h', () => {
    expect(pace('bike', 7.5)).toBe('27.0 km/h');
  });

  it('never shows 60 seconds', () => {
    expect(pace('run', 1000 / 359.7)).toBe('6:00 /km');
  });

  it('shows no value when stopped or missing', () => {
    expect(pace('run', 0)).toBe('—');
    expect(pace('run', null)).toBe('—');
  });
});

describe('numbers', () => {
  it('rounds whole numbers with Indian grouping', () => {
    expect(whole(1800.4)).toBe('1,800');
    expect(whole(100000)).toBe('1,00,000');
    expect(whole(null)).toBe('—');
  });

  it('marks signs without a negative zero', () => {
    expect(signed(3)).toBe('+3');
    expect(signed(-12.6)).toBe('−13');
    expect(signed(-0.2)).toBe('0');
    expect(signed(1.26, 1)).toBe('+1.3');
  });
});

describe('dates', () => {
  it('formats headings', () => {
    expect(dayHeading('2026-11-05')).toBe('THU 5 NOV');
    expect(shortDate('2026-11-05')).toBe('5 Nov');
    expect(longDate('2027-11-01')).toBe('1 NOV 2027');
  });

  it('describes recent days in words', () => {
    expect(relativeDay('2026-11-05', '2026-11-05')).toBe('Today');
    expect(relativeDay('2026-11-04', '2026-11-05')).toBe('Yesterday');
    expect(relativeDay('2026-11-02', '2026-11-05')).toBe('Mon');
    expect(relativeDay('2026-09-25', '2026-11-05')).toBe('25 Sep');
  });

  it('shows local time from the recorded offset, whatever time zone this device is in', () => {
    expect(localClock('2026-09-25T00:40:00Z', 330)).toBe('6:10 AM');
    expect(localClock('2026-09-25T13:45:00Z', 330)).toBe('7:15 PM');
    expect(localClock('2026-09-24T18:30:00Z', 330)).toBe('12:00 AM');
    expect(localClock('2026-09-25T06:30:00Z', 330)).toBe('12:00 PM');
  });

  it('shows a named time zone', () => {
    expect(zonedClock('2026-11-05T02:12:00Z', 'Asia/Kolkata')).toBe('7:42 AM');
    expect(zonedDate('2026-11-05T20:00:00Z', 'Asia/Kolkata')).toBe('2026-11-06');
  });
});

describe('12-hour picker', () => {
  it.each([
    ['07:30', { hour: 7, minute: '30', period: 'AM' }],
    ['00:15', { hour: 12, minute: '15', period: 'AM' }],
    ['12:00', { hour: 12, minute: '00', period: 'PM' }],
    ['19:45', { hour: 7, minute: '45', period: 'PM' }],
  ])('converts %s both ways', (value, expected) => {
    expect(to12Hour(value)).toEqual(expected);
    expect(to24Hour(expected.hour, expected.minute, expected.period)).toBe(value);
  });
});

describe('countdown', () => {
  it('splits seconds into parts', () => {
    // 360 days, 16 h, 30 min and 5 s.
    expect(countdownParts(360 * 86400 + 16 * 3600 + 30 * 60 + 5)).toEqual({
      days: '360',
      hours: '16',
      minutes: '30',
      seconds: '05',
    });
  });

  it('stops at zero', () => {
    expect(countdownParts(-5)).toEqual({ days: '0', hours: '00', minutes: '00', seconds: '00' });
  });
});

describe('resting HR wording', () => {
  it('compares with the baseline', () => {
    expect(restingDifference(-1.2)).toBe('1 below your baseline');
    expect(restingDifference(2.4)).toBe('2 above your baseline');
    expect(restingDifference(0.2)).toBe('At your baseline');
    expect(restingDifference(null)).toBe('No baseline yet');
  });
});
