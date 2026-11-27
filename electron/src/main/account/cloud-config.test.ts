import { expect, it } from 'vitest';
import {
  cloudAccountsAvailable,
  cloudOrigins,
  dashboardLinks,
  resolveCloudEnvironment,
} from './cloud-config';

it('packaged builds are locked to production whatever the env var says', () => {
  expect(resolveCloudEnvironment({ packaged: true, requested: 'local' }).name).toBe('prod');
});

it('developer builds honour VOICESTUDIO_CLOUD_ENV and default to production', () => {
  expect(resolveCloudEnvironment({ packaged: false, requested: 'local' }).issuer).toBe(
    'http://localhost:8092',
  );
  expect(resolveCloudEnvironment({ packaged: false }).name).toBe('prod');
  expect(resolveCloudEnvironment({ packaged: false, requested: 'bogus' }).name).toBe('prod');
});

it('ships WisprStudio offline-only by default with zero voicestudio.sh endpoints', () => {
  for (const requested of ['prod', 'dev', 'local'] as const) {
    const env = resolveCloudEnvironment({ packaged: false, requested });
    expect(env.clientId).toBe('');
    expect(cloudAccountsAvailable(env)).toBe(false);
    for (const origin of cloudOrigins(env)) {
      expect(origin).not.toContain('voicestudio.sh');
    }
  }
  expect(cloudAccountsAvailable(resolveCloudEnvironment({ packaged: true }))).toBe(false);
});

it('honours a runtime client ID override only in non-packaged builds', () => {
  expect(
    resolveCloudEnvironment({
      packaged: false,
      requested: 'local',
      clientId: ' 123456 ',
    }).clientId,
  ).toBe('123456');
  expect(resolveCloudEnvironment({ packaged: true, clientId: 'attacker' }).clientId).toBe('');
});

it('computes deterministic dashboard sub-paths from configured loopback origin', () => {
  expect(dashboardLinks(resolveCloudEnvironment({ packaged: true }))).toEqual({
    profile: 'http://127.0.0.1:3000/settings/profile',
    deletion: 'http://127.0.0.1:3000/settings/deletion-review',
    plan: 'http://127.0.0.1:3000/settings/plan',
  });
});

it('rejects a malformed account config (non-loopback plain HTTP or non-numeric clientId)', async () => {
  const { parseAccountConfig, ACCOUNT_CONFIG } =
    await import('../../../../config/account-config.mjs');
  const good = JSON.parse(JSON.stringify(ACCOUNT_CONFIG));
  expect(() => parseAccountConfig(good)).not.toThrow();
  const broken = (mutate: (c: typeof good) => void) => {
    const copy = JSON.parse(JSON.stringify(good));
    mutate(copy);
    return () => parseAccountConfig(copy);
  };
  expect(broken((c) => (c.environments.prod.issuer = 'http://id.example.com'))).toThrow();
  expect(broken((c) => (c.environments.prod.clientId = 'not-numeric'))).toThrow();
});
