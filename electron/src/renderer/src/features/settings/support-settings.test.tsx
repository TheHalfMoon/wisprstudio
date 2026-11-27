import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
const mock = vi.hoisted(() => ({ open: vi.fn().mockResolvedValue(undefined), navigate: vi.fn() }));
vi.mock('@/components/bridge', () => ({
  getBridge: () => ({ files: { openExternal: mock.open } }),
}));
vi.mock('react-i18next', async (importOriginal) => ({
  ...(await importOriginal<typeof import('react-i18next')>()),
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock('@tanstack/react-router', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@tanstack/react-router')>()),
  useSearch: () => ({}),
  useNavigate: () => mock.navigate,
}));
import { SupportSettings } from './support-settings';
vi.mock('./donation-goal', () => ({ DonationGoal: () => null }));
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});
it('opens only explicit WisprStudio repository destinations without Pro upsells', () => {
  render(<SupportSettings />);
  expect(mock.open).not.toHaveBeenCalled();
  const paypal = screen.getByRole('link', { name: 'PayPal' });
  expect(paypal).toHaveAttribute('href', 'https://github.com/TheHalfMoon/wisprstudio/discussions');
  fireEvent.click(screen.getByRole('button', { name: '$20' }));
  expect(paypal).toHaveAttribute(
    'href',
    'https://github.com/TheHalfMoon/wisprstudio/discussions',
  );
  expect(screen.getByRole('link', { name: 'Ko-fi' })).toHaveAttribute(
    'href',
    'https://github.com/TheHalfMoon/wisprstudio#support',
  );
  const sponsors = screen.getAllByRole('link', { name: 'GitHub Sponsors' });
  expect(sponsors).toHaveLength(2);
  for (const link of sponsors)
    expect(link).toHaveAttribute('href', 'https://github.com/TheHalfMoon/wisprstudio#sponsors');
  expect(
    within(screen.getByRole('group', { name: 'donate.choose_method' })).getAllByRole('link')[0],
  ).toBe(sponsors[0]);
  fireEvent.click(paypal);
  expect(mock.open).toHaveBeenCalledOnce();
  expect(mock.open).toHaveBeenCalledWith(
    'https://github.com/TheHalfMoon/wisprstudio/discussions',
  );
  expect(screen.getByRole('link', { name: 'contact.security_cta' })).toHaveAttribute(
    'href',
    'https://github.com/TheHalfMoon/wisprstudio/security/advisories/new',
  );
  expect(screen.getByRole('link', { name: 'support.sponsors_become' })).toHaveAttribute(
    'href',
    'https://github.com/TheHalfMoon/wisprstudio/issues',
  );
  expect(screen.queryByRole('button', { name: 'supportPlans.get_pro' })).toBeNull();
});

it('keeps contact and AGPLv3 source links visible and lets the donor clear an amount', () => {
  render(<SupportSettings />);
  expect(screen.getByRole('link', { name: 'contact.security_cta' })).toBeVisible();
  expect(screen.getByRole('button', { name: 'donate.custom' })).toHaveAttribute(
    'aria-pressed',
    'false',
  );
  const amount = screen.getByRole('button', { name: '$50' });
  fireEvent.click(amount);
  expect(amount).toHaveAttribute('aria-pressed', 'true');
  fireEvent.click(amount);
  expect(amount).toHaveAttribute('aria-pressed', 'false');
  expect(screen.getByRole('link', { name: 'PayPal' })).toHaveAttribute(
    'href',
    'https://github.com/TheHalfMoon/wisprstudio/discussions',
  );
  fireEvent.click(screen.getByRole('button', { name: 'donate.custom' }));
  expect(screen.getByRole('link', { name: 'PayPal' })).toHaveAttribute(
    'href',
    'https://github.com/TheHalfMoon/wisprstudio/discussions',
  );
});
