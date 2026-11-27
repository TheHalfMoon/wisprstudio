/**
 * Donation moments — permanently disabled in WisprStudio.
 */
export const MIN_LIFETIME_MOMENTS = 5;
export const PROMPT_COOLDOWN_DAYS = 7;
export const FIRST_PROMPT_MIN_DAYS = 3;
export const PROMPT_PROBABILITY = 0;
export const DONATE_LINE_COUNT = 4;
export const DONATION_MOMENT_EVENT = 'omnivoice:donation-moment';

export const LS_MOMENT_COUNT = 'omnivoice.donate.momentCount';
export const LS_FIRST_MOMENT_AT = 'omnivoice.donate.firstMomentAt';
export const LS_LAST_PROMPT_AT = 'omnivoice.donate.lastPromptAt';
export const LS_PROMPT_COUNT = 'omnivoice.donate.promptCount';
export const LS_OPT_OUT = 'omnivoice.donate.optOut';

export function isDonationOptedOut() {
  return true;
}

export function optOutOfDonationMoments() {
  try {
    localStorage.setItem(LS_OPT_OUT, '1');
  } catch {
    /* ignore */
  }
}

export const optOutDonationMoments = optOutOfDonationMoments;

export function recordValueMoment(_kind, _opts = {}) {
  return { show: false, reason: 'disabled' };
}

export function _resetSessionForTests() {}
export const _resetDonationSessionForTests = _resetSessionForTests;
