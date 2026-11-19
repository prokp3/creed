import { describe, expect, it } from 'vitest';
import { widgetScript } from './widgetscript.js';

const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor;
const KEY = 'creed_w_Ab3-x_Yz09';

describe('widgetScript', () => {
  it('fills in the address and key', () => {
    const script = widgetScript('https://creed.example/', KEY);
    expect(script).toContain('const CREED = "https://creed.example";');
    expect(script).toContain(`const KEY = "${KEY}";`);
    expect(script).not.toContain('__CREED__');
    expect(script).not.toContain('__KEY__');
  });

  it('is valid JavaScript for Scriptable to run', () => {
    expect(() => new AsyncFunction(widgetScript('http://localhost:5173', KEY))).not.toThrow();
  });

  it('keeps anything that could break out of the strings out', () => {
    const script = widgetScript('https://creed.example"; evil()', 'creed_w_"+x');
    expect(script).toContain('const CREED = "https://creed.exampleevil";');
    expect(script).toContain('const KEY = "creed_w_x";');
  });

  it('sends the key in a header, not the address', () => {
    const script = widgetScript('https://creed.example', KEY);
    expect(script).toContain('Authorization: "Bearer " + KEY');
    expect(script).toContain('new Request(CREED + "/api/widget/food")');
  });
});
