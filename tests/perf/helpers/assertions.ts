import { expect } from '@playwright/test';

export interface AddressMatch {
  uuid?: string | null;
  address: string;
  unit?: string | null;
  city?: string | null;
  county?: string | null;
  state?: string | null;
  zip?: string | null;
  latitude?: number | null;
  longitude?: number | null;
  score: number;
}

export function assertMatchShape(matches: unknown): asserts matches is AddressMatch[] {
  expect(Array.isArray(matches)).toBe(true);
  const arr = matches as AddressMatch[];
  expect(arr.length).toBeGreaterThan(0);
  expect(arr.length).toBeLessThanOrEqual(3);
  for (const m of arr) {
    expect(typeof m.address).toBe('string');
    expect(typeof m.score).toBe('number');
  }
  for (let i = 1; i < arr.length; i++) {
    expect(arr[i - 1].score).toBeGreaterThanOrEqual(arr[i].score);
  }
}

export function assertTopMatch(
  matches: AddressMatch[],
  opts: {
    addressContains?: string;
    minScore?: number;
    state?: string;
    cityContains?: string;
  },
): void {
  assertMatchShape(matches);
  const top = matches[0];
  if (opts.addressContains) {
    expect(top.address.toLowerCase()).toContain(opts.addressContains.toLowerCase());
  }
  if (opts.minScore !== undefined) {
    expect(top.score).toBeGreaterThanOrEqual(opts.minScore);
  }
  if (opts.state) {
    expect(top.state?.toUpperCase()).toBe(opts.state.toUpperCase());
  }
  if (opts.cityContains) {
    expect((top.city ?? '').toLowerCase()).toContain(opts.cityContains.toLowerCase());
  }
}
