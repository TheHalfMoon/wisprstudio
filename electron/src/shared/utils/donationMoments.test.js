import { describe, it, expect, beforeEach } from 'vitest';
import {
  recordValueMoment,
  optOutDonationMoments,
  isDonationOptedOut,
  _resetDonationSessionForTests,
  DONATION_MOMENT_EVENT,
} from './donationMoments';

describe('donationMoments — permanently silenced in WisprStudio', () => {
  beforeEach(() => {
    localStorage.clear();
    _resetDonationSessionForTests();
  });

  it('never prompts or dispatches donation-moment popovers', () => {
    let dispatched = 0;
    const onEvent = () => {
      dispatched += 1;
    };
    window.addEventListener(DONATION_MOMENT_EVENT, onEvent);
    try {
      for (let i = 0; i < 20; i += 1) {
        expect(recordValueMoment('export', { random: () => 0 })).toEqual({
          show: false,
          reason: 'disabled',
        });
      }
      expect(dispatched).toBe(0);
    } finally {
      window.removeEventListener(DONATION_MOMENT_EVENT, onEvent);
    }
  });

  it('always reports opted-out so legacy callers stay quiet', () => {
    expect(isDonationOptedOut()).toBe(true);
    expect(() => optOutDonationMoments()).not.toThrow();
    expect(isDonationOptedOut()).toBe(true);
  });
});
