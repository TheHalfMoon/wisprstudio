import { describe, expect, it } from 'vitest';
import html from '../index.html?raw';

describe('renderer content security policy', () => {
  it('blocks PostHog telemetry and live GitHub API beacons in connect-src', () => {
    expect(html).toContain("connect-src 'self' blob: ws: http://localhost:* http://127.0.0.1:*");
    expect(html).not.toContain(['posthog', 'com'].join('.'));
    expect(html).not.toContain('api.github.com');
    expect(html).not.toContain('voicestudio.sh');
  });
});
