import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';

const openExternal = vi.hoisted(() => vi.fn(async () => {}));
let bridgeEnabled = false;
vi.mock('@/components/bridge', () => ({
  getBridge: () => (bridgeEnabled ? { files: { openExternal } } : null),
}));
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }));

import { GithubStar } from './github-star';

afterEach(() => {
  cleanup();
  bridgeEnabled = false;
  openExternal.mockClear();
  vi.unstubAllGlobals();
});

it('renders a static AGPLv3 repository link with zero live GitHub API requests', () => {
  const fetchSpy = vi.fn();
  vi.stubGlobal('fetch', fetchSpy);
  render(<GithubStar />);
  const link = screen.getByRole('link', { name: 'support.star_github' });
  expect(link).toHaveAttribute('href', 'https://github.com/TheHalfMoon/wisprstudio');
  expect(screen.getByText('AGPLv3')).toBeVisible();
  expect(fetchSpy).not.toHaveBeenCalled();
});

it('opens the repository externally through the desktop bridge when clicked', () => {
  bridgeEnabled = true;
  render(<GithubStar />);
  fireEvent.click(screen.getByRole('link', { name: 'support.star_github' }));
  expect(openExternal).toHaveBeenCalledWith('https://github.com/TheHalfMoon/wisprstudio');
});
