import React from 'react';
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, act } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

vi.mock('../api/hooks', async (importOriginal) => ({
  ...(await importOriginal()),
  useSystemLogs: () => ({ data: null, refetch: vi.fn() }),
  useTauriLogs: () => ({ data: null, refetch: vi.fn() }),
  useNotifications: () => ({ data: null }),
  useVisibleNotifications: () => ({ data: null, notifications: [] }),
  isDismissibleNotification: () => false,
}));
vi.mock('../api/system', async (importOriginal) => ({
  ...(await importOriginal()),
  clearSystemLogs: vi.fn(),
  clearTauriLogs: vi.fn(),
}));
vi.mock('../components/NetworkToggle', () => ({ default: () => null }));
vi.mock('../api/external', () => ({ openExternal: vi.fn() }));

import LogsFooter from '../components/LogsFooter';
import DonateMomentPopover from '../components/DonateMomentPopover';
import { DONATION_MOMENT_EVENT, recordValueMoment } from '../utils/donationMoments';

beforeEach(() => {
  localStorage.clear();
});

describe('LogsFooter — donation-moment popovers permanently disabled in WisprStudio', () => {
  it('renders DonateMomentPopover as null even when events are dispatched', () => {
    const { container } = render(<DonateMomentPopover open line={0} onClose={vi.fn()} />);
    expect(container.firstChild).toBeNull();
  });

  it('never displays a donate-moment-popover in LogsFooter', () => {
    render(
      <QueryClientProvider
        client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
      >
        <LogsFooter />
      </QueryClientProvider>,
    );
    act(() => {
      window.dispatchEvent(
        new CustomEvent(DONATION_MOMENT_EVENT, { detail: { kind: 'export', line: 0 } }),
      );
      expect(recordValueMoment('export', { random: () => 0 })).toEqual({
        show: false,
        reason: 'disabled',
      });
    });
    expect(screen.queryByTestId('donate-moment-popover')).toBeNull();
  });
});
