// Units are metric and clocks are 12-hour. These are pure functions, tested in format.test.js.

export const DASH = '—';
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const WEEKDAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];

export const pad2 = (n) => String(n).padStart(2, '0');

const isNumber = (n) => typeof n === 'number' && Number.isFinite(n);

export const whole = (n) => (isNumber(n) ? Math.round(n).toLocaleString('en-IN') : DASH);

/** Seconds as h:mm, such as 5:48. */
export function clock(seconds) {
  if (!isNumber(seconds)) return DASH;
  const minutes = Math.round(seconds / 60);
  return `${Math.floor(minutes / 60)}:${pad2(minutes % 60)}`;
}

/** Seconds in words, such as 5h 48m or 55m. */
export function duration(seconds) {
  if (!isNumber(seconds)) return DASH;
  const minutes = Math.round(seconds / 60);
  const hours = Math.floor(minutes / 60);
  return hours ? `${hours}h ${pad2(minutes % 60)}m` : `${minutes}m`;
}

/** Swims in metres, everything else in kilometres. */
export function distance(discipline, metres) {
  if (!isNumber(metres)) return DASH;
  if (discipline === 'swim') return `${Math.round(metres).toLocaleString('en-IN')} m`;
  const km = metres / 1000;
  return `${km >= 100 || Number.isInteger(km) ? Math.round(km) : km.toFixed(1)} km`;
}

function minutesAndSeconds(totalSeconds) {
  let minutes = Math.floor(totalSeconds / 60);
  let seconds = Math.round(totalSeconds - minutes * 60);
  if (seconds === 60) {
    minutes += 1;
    seconds = 0;
  }
  return `${minutes}:${pad2(seconds)}`;
}

/** Run pace, swim pace or bike speed, each in the unit that sport uses. */
export function pace(discipline, metresPerSecond) {
  if (!isNumber(metresPerSecond) || metresPerSecond <= 0) return DASH;
  if (discipline === 'bike') return `${(metresPerSecond * 3.6).toFixed(1)} km/h`;
  if (discipline === 'swim') return `${minutesAndSeconds(100 / metresPerSecond)} /100 m`;
  return `${minutesAndSeconds(1000 / metresPerSecond)} /km`;
}

export function signed(n, digits = 0) {
  if (!isNumber(n)) return DASH;
  const text = Math.abs(n).toFixed(digits);
  if (Number(text) === 0) return text;
  return `${n > 0 ? '+' : '−'}${text}`;
}

function parts(isoDate) {
  const [year, month, day] = isoDate.slice(0, 10).split('-').map(Number);
  return { year, month, day, weekday: new Date(Date.UTC(year, month - 1, day)).getUTCDay() };
}

/** THU 5 NOV */
export function dayHeading(isoDate) {
  const { month, day, weekday } = parts(isoDate);
  return `${WEEKDAYS[weekday]} ${day} ${MONTHS[month - 1]}`.toUpperCase();
}

/** 5 Nov */
export function shortDate(isoDate) {
  const { month, day } = parts(isoDate);
  return `${day} ${MONTHS[month - 1]}`;
}

/** 1 NOV 2027 */
export function longDate(isoDate) {
  const { year, month, day } = parts(isoDate);
  return `${day} ${MONTHS[month - 1]} ${year}`.toUpperCase();
}

/** Today, Yesterday, a weekday within the last week, or a date. */
export function relativeDay(isoDate, today) {
  const a = parts(isoDate);
  const b = parts(today);
  const days = Math.round((Date.UTC(b.year, b.month - 1, b.day) - Date.UTC(a.year, a.month - 1, a.day)) / 86400000);
  if (days === 0) return 'Today';
  if (days === 1) return 'Yesterday';
  if (days > 1 && days < 7) return WEEKDAYS[a.weekday];
  return shortDate(isoDate);
}

/** 6:10 AM, from a UTC instant and the offset recorded with it. */
export function localClock(isoInstant, offsetMinutes) {
  if (!isoInstant || !isNumber(offsetMinutes)) return '';
  const local = new Date(new Date(isoInstant).getTime() + offsetMinutes * 60000);
  const hour = local.getUTCHours();
  return `${hour % 12 || 12}:${pad2(local.getUTCMinutes())} ${hour < 12 ? 'AM' : 'PM'}`;
}

/** 7:42 AM in a named time zone. */
export function zonedClock(isoInstant, timeZone) {
  if (!isoInstant) return '';
  return new Intl.DateTimeFormat('en-US', { hour: 'numeric', minute: '2-digit', hour12: true, timeZone }).format(
    new Date(isoInstant),
  );
}

/** The date of an instant in a named time zone, as yyyy-mm-dd. */
export function zonedDate(isoInstant, timeZone) {
  return new Intl.DateTimeFormat('en-CA', { year: 'numeric', month: '2-digit', day: '2-digit', timeZone }).format(
    new Date(isoInstant),
  );
}

export function zoneAbbreviation(timeZone) {
  const part = new Intl.DateTimeFormat('en-IN', { timeZone, timeZoneName: 'short' })
    .formatToParts(new Date())
    .find((p) => p.type === 'timeZoneName');
  return part ? part.value : timeZone;
}

/** 24-hour 07:30 to the three parts of a 12-hour picker. */
export function to12Hour(value) {
  const [hours, minute] = value.split(':');
  const hour24 = Number(hours);
  return { hour: hour24 % 12 || 12, minute, period: hour24 < 12 ? 'AM' : 'PM' };
}

export function to24Hour(hour, minute, period) {
  const base = Number(hour) % 12;
  return `${pad2(period === 'PM' ? base + 12 : base)}:${minute}`;
}

export function countdownParts(totalSeconds) {
  const left = Math.max(0, Math.floor(totalSeconds));
  return {
    days: String(Math.floor(left / 86400)),
    hours: pad2(Math.floor((left % 86400) / 3600)),
    minutes: pad2(Math.floor((left % 3600) / 60)),
    seconds: pad2(left % 60),
  };
}

export function restingDifference(difference) {
  if (!isNumber(difference)) return 'No baseline yet';
  const rounded = Math.round(Math.abs(difference));
  if (rounded === 0) return 'At your baseline';
  return `${rounded} ${difference < 0 ? 'below' : 'above'} your baseline`;
}

export function titleCase(text) {
  if (!text) return '';
  return text
    .toLowerCase()
    .replaceAll('_', ' ')
    .replace(/^\w/, (c) => c.toUpperCase());
}
