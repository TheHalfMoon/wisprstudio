import React from 'react';
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';

const { openExternal } = vi.hoisted(() => ({ openExternal: vi.fn() }));
vi.mock('../api/external', () => ({ openExternal }));

vi.mock('../api/donation', async (importOriginal) => {
  const actual = await importOriginal();
  return { ...actual, loadDonationProgress: vi.fn().mockResolvedValue(actual.BUNDLED_PROGRESS) };
});

let mockSponsors = [];
vi.mock('../config/sponsors', async (importOriginal) => {
  const actual = await importOriginal();
  return {
    ...actual,
    get SPONSORS() {
      return mockSponsors;
    },
  };
});

import SupportPage from '../pages/SupportPage';
import { SPONSOR_CONTACT } from '../config/sponsors';

const renderSupport = () => render(<SupportPage initialView="support" onBack={vi.fn()} />);

beforeEach(() => {
  mockSponsors = [];
  openExternal.mockClear();
});

describe('SupportPage — Sponsors', () => {
  it('renders the outlined placeholder when the roster is empty', async () => {
    renderSupport();
    expect(await screen.findByTestId('sponsors-empty')).toBeInTheDocument();
    expect(screen.getByText(/Be the first to sponsor WisprStudio/i)).toBeInTheDocument();
    expect(screen.getByText(/Your logo here/i)).toBeInTheDocument();
  });

  it('"Become a sponsor" opens the WisprStudio repository issues URL', async () => {
    renderSupport();
    await screen.findByTestId('sponsors-empty');
    fireEvent.click(screen.getByRole('button', { name: /become a sponsor/i }));
    expect(openExternal).toHaveBeenCalledWith(SPONSOR_CONTACT.githubIssue);
    expect(SPONSOR_CONTACT.githubIssue).toBe('https://github.com/TheHalfMoon/wisprstudio/issues');
  });

  it('renders each sponsor as an external logo link when the roster is populated', async () => {
    mockSponsors = [
      {
        name: 'Acme Corp',
        logoUrl: 'https://acme.example/logo.svg',
        url: 'https://acme.example',
        tier: 'strategic',
      },
      {
        name: 'Globex',
        logoUrl: 'https://globex.example/logo.png',
        url: 'https://globex.example',
        tier: 'company',
      },
    ];
    renderSupport();

    expect(screen.queryByTestId('sponsors-empty')).toBeNull();

    const acme = await screen.findByLabelText('Visit Acme Corp, a WisprStudio sponsor');
    const globex = screen.getByLabelText('Visit Globex, a WisprStudio sponsor');

    expect(acme).toHaveAttribute('href', 'https://acme.example');
    expect(acme).toHaveAttribute('rel', 'noreferrer');
    const img = screen.getByAltText('Acme Corp');
    expect(img).toHaveAttribute('src', 'https://acme.example/logo.svg');
    expect(img).toHaveAttribute('loading', 'lazy');

    fireEvent.click(globex);
    expect(openExternal).toHaveBeenCalledWith('https://globex.example');
  });
});
