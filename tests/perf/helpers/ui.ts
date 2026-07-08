import { expect, Page } from '@playwright/test';

export const selectors = {
  query: '#query',
  searchBtn: '#searchBtn',
  submitBtn: '#submitBtn',
  results: '#results',
  resultList: '#resultList',
  message: '#message',
  selectionHint: '#selectionHint',
  resultRow: '.result',
  refreshBtn: '#refreshBtn',
  nadTotal: '#nadTotal',
  nadByState: '#nadByState',
  nadByCounty: '#nadByCounty',
  nadSubTotal: '#subTotal',
  subByState: '#subByState',
  subByCounty: '#subByCounty',
} as const;

export async function searchAddress(page: Page, query: string): Promise<void> {
  await page.fill(selectors.query, query);
  await page.click(selectors.searchBtn);
}

export async function waitForResults(page: Page, timeoutMs = 60_000): Promise<void> {
  await expect(page.locator(selectors.results)).toBeVisible({ timeout: timeoutMs });
  await expect(page.locator(selectors.resultRow).first()).toBeVisible({ timeout: timeoutMs });
}

export async function selectResult(page: Page, index: number): Promise<void> {
  const row = page.locator(selectors.resultRow).nth(index);
  await row.click();
  await expect(page.locator(selectors.submitBtn)).toBeEnabled();
}

export async function submitSelection(page: Page): Promise<void> {
  await page.click(selectors.submitBtn);
}

export async function expectBanner(page: Page, kind: 'error' | 'info' | 'success'): Promise<void> {
  await expect(page.locator(`${selectors.message} .banner.${kind}`)).toBeVisible();
}

export async function expectNoResults(page: Page): Promise<void> {
  await expect(page.locator(selectors.results)).toBeHidden();
}

export function resultCount(page: Page) {
  return page.locator(selectors.resultRow);
}
