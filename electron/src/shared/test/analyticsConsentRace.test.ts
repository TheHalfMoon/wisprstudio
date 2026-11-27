import { expect, it, vi } from 'vitest';

it('keeps enableAnalytics and disableAnalytics as offline no-ops with zero posthog-js imports', async () => {
  vi.resetModules();
  const imported = vi.fn(() => {
    throw new Error('posthog-js must never be dynamically imported');
  });
  vi.doMock('posthog-js/dist/module.slim.no-external', imported);
  vi.doMock('posthog-js/dist/extension-bundles', imported);
  try {
    const analytics = await import('../utils/analytics');
    expect(analytics.analyticsAvailable()).toBe(false);
    await expect(analytics.enableAnalytics()).resolves.toBeUndefined();
    expect(analytics.analyticsAvailable()).toBe(false);
    analytics.disableAnalytics();
    expect(analytics.analyticsAvailable()).toBe(false);
    await expect(
      analytics.initAnalyticsFromConsent(async () => ({ opted_in: true, available: true })),
    ).resolves.toBe(false);
    expect(analytics.analyticsAvailable()).toBe(false);
    expect(imported).not.toHaveBeenCalled();
  } finally {
    vi.doUnmock('posthog-js/dist/module.slim.no-external');
    vi.doUnmock('posthog-js/dist/extension-bundles');
  }
});
