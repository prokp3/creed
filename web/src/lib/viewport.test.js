import { describe, expect, it } from 'vitest';
import { fillTheScreen } from './viewport.js';

const IPHONE = 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X)';
const IPAD = 'Mozilla/5.0 (iPad; CPU OS 18_0 like Mac OS X)';

function fakeWindow({ userAgent = IPHONE, standalone = true, portrait = true } = {}) {
  const set = {};
  const listeners = {};
  return {
    set,
    listeners,
    navigator: { userAgent, standalone },
    screen: { width: 402, height: 874 },
    matchMedia: (query) => ({ matches: query.includes('portrait') ? portrait : standalone }),
    addEventListener: (name, handler) => (listeners[name] = handler),
    document: { documentElement: { style: { setProperty: (name, value) => (set[name] = value) } } },
  };
}

describe('fillTheScreen', () => {
  it('uses the full screen height in an iPhone home-screen app', () => {
    const win = fakeWindow();
    expect(fillTheScreen(win)).toBe(true);
    expect(win.set['--app-height']).toBe('874px');
  });

  it('uses the short side in landscape, and follows turning the phone', () => {
    const win = fakeWindow({ portrait: false });
    fillTheScreen(win);
    expect(win.set['--app-height']).toBe('402px');
    expect(win.listeners.resize).toBeTypeOf('function');
  });

  it('leaves Safari alone, where toolbars take up part of the screen', () => {
    const win = fakeWindow({ standalone: false });
    expect(fillTheScreen(win)).toBe(false);
    expect(win.set).toEqual({});
  });

  it('leaves iPad alone, where the app may not fill the screen', () => {
    const win = fakeWindow({ userAgent: IPAD });
    expect(fillTheScreen(win)).toBe(false);
    expect(win.set).toEqual({});
  });
});
