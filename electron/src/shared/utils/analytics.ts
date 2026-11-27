/**
 * Frontend analytics stub for WisprStudio — permanently disabled.
 *
 * WisprStudio ships with zero outbound telemetry, zero PostHog tokens, and no
 * posthog-js initialization. Helper signatures remain exported so call sites
 * across the renderer stay type-safe with zero network activity.
 */
import { scrubText } from './scrub';

const PUBLIC_PROJECT_TOKEN = '';
const POSTHOG_TOKEN = '';
const POSTHOG_HOST = '';

/** Analytics is permanently unavailable in WisprStudio. */
export function analyticsAvailable(): boolean {
  return false;
}

const ALLOWED_PROPS = new Set([
  'engine_id',
  'language',
  'mode',
  'kind',
  'source',
  'input_type',
  'effect_preset',
  'error_type',
  'duration_seconds',
  'gen_time_seconds',
  'text_length',
  'has_profile',
  'stream',
  'app_version',
  'platform',
  'from_version',
  'to_version',
  'exit_kind',
  'uptime_bucket',
  'error_class',
  'stage',
  'install_channel',
]);

const MAX_STR_LEN = 64;

const URL_PROPERTIES = [
  '$current_url',
  '$pathname',
  '$host',
  '$title',
  '$referrer',
  '$referring_domain',
  '$initial_current_url',
  '$initial_pathname',
  '$initial_referrer',
  '$initial_referring_domain',
] as const;

interface OutgoingAnalyticsEvent {
  event?: string;
  properties?: Record<string, unknown>;
}

/** Strip renderer URLs and document metadata from any synthetic payload. */
export function sanitizeOutgoingEvent<T extends OutgoingAnalyticsEvent>(
  payload: T | null,
): T | null {
  if (!payload) return null;
  const properties = { ...payload.properties };
  for (const key of URL_PROPERTIES) delete properties[key];
  return { ...payload, properties };
}

export const ANALYTICS_EXCEPTION_STAGES = [
  'renderer:uncaught',
  'renderer:rejection',
  'renderer:react-boundary',
  'renderer:task',
] as const;

export type AnalyticsExceptionStage = (typeof ANALYTICS_EXCEPTION_STAGES)[number];

const MAX_STACK_LINES = 40;
const MAX_STACK_LINE_LENGTH = 512;

function safeErrorClass(error: unknown): string {
  const candidate = error instanceof Error ? error.name : 'Error';
  return /^[A-Za-z][A-Za-z0-9_.-]{0,63}$/.test(candidate) ? candidate : 'Error';
}

export function sanitizeException(error: unknown): Error {
  const errorClass = safeErrorClass(error);
  const sourceStack = error instanceof Error && typeof error.stack === 'string' ? error.stack : '';
  const frames = scrubText(sourceStack)
    .split('\n')
    .slice(1)
    .filter((line) =>
      /^\s*at (?:[\w$.[\]<>]+ )?\(?(?:https?:\/\/|file:\/\/|app:\/\/|~?\/)[^()\s]+:\d+:\d+\)?$/.test(
        line,
      ),
    )
    .slice(0, MAX_STACK_LINES)
    .map((line) => line.slice(0, MAX_STACK_LINE_LENGTH));
  const safe = new Error('WisprStudio renderer error');
  safe.name = errorClass;
  safe.stack = [`${errorClass}: WisprStudio renderer error`, ...frames].join('\n');
  return safe;
}

export function captureException(_error: unknown, _stage: AnalyticsExceptionStage): void {
  /* Telemetry permanently disabled. */
}

export function sanitizeProps(props?: Record<string, unknown>): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(props ?? {})) {
    if (!ALLOWED_PROPS.has(k)) continue;
    if (typeof v === 'string' && v.length > MAX_STR_LEN) continue;
    if (v === null || ['string', 'number', 'boolean'].includes(typeof v)) out[k] = v;
  }
  return out;
}

export function hardenedConfig() {
  return {
    api_host: POSTHOG_HOST,
    autocapture: false,
    disable_session_recording: true,
    capture_exceptions: false,
    capture_pageview: false,
    capture_pageleave: false,
    mask_all_text: true,
    mask_all_element_attributes: true,
    opt_out_capturing_by_default: true,
    persistence: 'localStorage' as const,
    before_send: sanitizeOutgoingEvent,
  };
}

export async function enableAnalytics(): Promise<void> {
  void PUBLIC_PROJECT_TOKEN;
  void POSTHOG_TOKEN;
}

export function disableAnalytics(): void {
  /* Telemetry permanently disabled. */
}

export function capture(_event: string, _props?: Record<string, unknown>): void {
  /* Telemetry permanently disabled. */
}

export function capturePageview(_screen: string): void {
  /* Telemetry permanently disabled. */
}

export async function initAnalyticsFromConsent(
  _fetchState: () => Promise<{ opted_in?: boolean; available?: boolean }>,
): Promise<boolean> {
  return false;
}
