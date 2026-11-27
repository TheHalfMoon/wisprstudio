import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, string>) => {
      const table: Record<string, string> = {
        'app.name': 'WisprStudio',
        'pro.license_badge': 'AGPL-3.0-only',
        'pro.open_source_heading': 'WisprStudio Free & Open-Source Software',
        'pro.open_source_body':
          'WisprStudio runs locally on your hardware with zero telemetry, no cloud account, and no paid closed-source tier.',
        'pro.source_code_cta': `Complete Corresponding Source Code (${opts?.url ?? ''})`,
      };
      return table[key] ?? key;
    },
  }),
}));
vi.mock('@/components/app-shell/workspace-header', () => ({
  WorkspaceHeader: ({ children }: { children: React.ReactNode }) => <header>{children}</header>,
}));
vi.mock('@/components/external-link', () => ({
  ExternalLink: ({ href, children }: { href: string; children: React.ReactNode }) => (
    <a href={href}>{children}</a>
  ),
}));

import { ProPage } from './pro-page';

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

it('replaces commercial Pro pricing with the AGPL-3.0-only open-source offer', () => {
  render(<ProPage />);
  expect(screen.queryByText('$99')).not.toBeInTheDocument();
  expect(screen.queryByText('$199')).not.toBeInTheDocument();
  expect(screen.getByText('AGPL-3.0-only')).toBeVisible();
  expect(
    screen.getByRole('heading', { level: 2, name: /WisprStudio Free & Open-Source Software/i }),
  ).toBeVisible();
  const sourceLink = screen.getByRole('link', { name: /Complete Corresponding Source Code/i });
  expect(sourceLink).toHaveAttribute('href', 'https://github.com/TheHalfMoon/wisprstudio');
});
