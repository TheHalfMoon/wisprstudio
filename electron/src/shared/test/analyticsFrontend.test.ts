import { describe, it, expect } from 'vitest';
import {
  analyticsAvailable,
  disableAnalytics,
  enableAnalytics,
  sanitizeException,
  sanitizeProps,
  capturePageview,
  sanitizeOutgoingEvent,
  hardenedConfig,
  initAnalyticsFromConsent,
} from '../utils/analytics';

describe('hardenedConfig & permanent telemetry disablement', () => {
  it('permanently disables analytics availability and all PostHog autocapture flags', () => {
    expect(analyticsAvailable()).toBe(false);
    const c = hardenedConfig();
    expect(c.api_host).toBe('');
    expect(c.autocapture).toBe(false);
    expect(c.disable_session_recording).toBe(true);
    expect(c.capture_exceptions).toBe(false);
    expect(c.capture_pageview).toBe(false);
    expect(c.capture_pageleave).toBe(false);
    expect(c.opt_out_capturing_by_default).toBe(true);
    expect(c.mask_all_text).toBe(true);
    expect(c.mask_all_element_attributes).toBe(true);
  });
});

describe('sanitizeProps — content cannot get out, even by accident', () => {
  it('drops anything not on the allowlist', () => {
    const clean = sanitizeProps({
      text: 'my private script about a confidential merger',
      audio_path: '/Users/someone/voice.wav',
      voice_name: "Grandma's voice",
      email: 'a@b.com',
      engine_id: 'omnivoice',
      language: 'en',
      text_length: 120,
      has_profile: true,
    });
    expect(clean).toEqual({
      engine_id: 'omnivoice',
      language: 'en',
      text_length: 120,
      has_profile: true,
    });
    const blob = JSON.stringify(clean);
    expect(blob).not.toContain('confidential');
    expect(blob).not.toContain('/Users/');
    expect(blob).not.toContain('Grandma');
  });

  it('refuses a long string even on an allowlisted key', () => {
    expect(sanitizeProps({ language: 'x'.repeat(500), engine_id: 'omnivoice' })).toEqual({
      engine_id: 'omnivoice',
    });
  });

  it('is safe on empty input', () => {
    expect(sanitizeProps()).toEqual({});
    expect(sanitizeProps({})).toEqual({});
  });
});

describe('sanitizeException — error tracking keeps frames, not user data', () => {
  it('replaces the message and removes credentials, home paths and extension frames', () => {
    const failure = new TypeError(
      'Private script at /home/pal/secret with token sk-12345678901234567890',
    );
    failure.stack = [
      failure.message,
      '    at render (/home/pal/github/WisprStudio/electron/src/app.tsx:12:3)',
      '    at extension (chrome-extension://private/content.js:2:1)',
    ].join('\n');
    const clean = sanitizeException(failure);
    expect(clean.name).toBe('TypeError');
    expect(clean.message).toBe('WisprStudio renderer error');
    expect(clean.stack).toContain('~/github/WisprStudio/electron/src/app.tsx:12:3');
    expect(clean.stack).not.toContain('Private script');
    expect(clean.stack).not.toContain('/home/pal');
    expect(clean.stack).not.toContain('sk-');
    expect(clean.stack).not.toContain('chrome-extension');
  });
});

describe('capturePageview & sanitizeOutgoingEvent', () => {
  it('is a safe no-op and strips all URL metadata', () => {
    expect(() => capturePageview('view:clone')).not.toThrow();
    const clean = sanitizeOutgoingEvent({
      event: '$pageview',
      properties: {
        stage: 'view:integrations',
        $current_url: 'http://localhost:3902/#/clone/private-id',
        $pathname: '/clone',
        $title: 'Private voice',
        $referrer: 'https://private.example/',
      },
    });
    expect(clean?.properties).toEqual({ stage: 'view:integrations' });
  });
});

describe('initAnalyticsFromConsent — permanently false in WisprStudio', () => {
  it('never starts analytics even if a caller passes opted_in:true', async () => {
    await enableAnalytics();
    disableAnalytics();
    expect(
      await initAnalyticsFromConsent(async () => ({
        available: true,
        opted_in: true,
      })),
    ).toBe(false);
    expect(
      await initAnalyticsFromConsent(async () => {
        throw new Error('backend down');
      }),
    ).toBe(false);
  });
});
