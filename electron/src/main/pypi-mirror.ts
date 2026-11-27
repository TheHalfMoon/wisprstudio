/**
 * PyPI lock URL helpers for WisprStudio.
 *
 * Unsolicited third-party PyPI mirrors (such as Aliyun) are disabled by policy;
 * locked wheels resolve exclusively against `files.pythonhosted.org` unless the
 * user explicitly configures their own `UV_INDEX_URL` environment variable.
 */

export const PYPI_FILES_ORIGIN = 'https://files.pythonhosted.org/packages/';

const PYPI_FILES_MIRRORS: Readonly<Record<string, string>> = {};

const KNOWN_MIRRORS = [...new Set(Object.values(PYPI_FILES_MIRRORS))];

const escape = (text: string) => text.replace(/[.*+?^${}()|[\]\\/]/g, '\\$&');

/** No unsolicited regional PyPI mirror is configured. */
export function pypiFilesMirror(region: string): string | null {
  return PYPI_FILES_MIRRORS[region] ?? null;
}

/** Host that serves the PyPI-hosted wheels for a resolved download region. */
export function pypiFilesHost(region: string): string {
  return new URL(pypiFilesMirror(region) ?? PYPI_FILES_ORIGIN).host;
}

export const PYPI_SPEED_SAMPLE_BYTES = 256 * 1024;
const PYPI_SPEED_TIMEOUT_MS = 6_000;
export const AUTO_PYPI_MIRROR: string | null = null;

export function speedSampleUrl(lock: string): string | null {
  for (const match of lock.matchAll(/\burl = "([^"]+\.whl)"[^}\n]*?\bsize = (\d+)/g)) {
    if (match[1]!.startsWith(PYPI_FILES_ORIGIN) && Number(match[2]) >= PYPI_SPEED_SAMPLE_BYTES)
      return match[1]!;
  }
  return null;
}

export type SampleTimer = (url: string, signal: AbortSignal) => Promise<number | null>;

export const timeSample: SampleTimer = async (url, signal) => {
  const started = performance.now();
  const timeout = AbortSignal.any([signal, AbortSignal.timeout(PYPI_SPEED_TIMEOUT_MS)]);
  try {
    const response = await fetch(url, {
      redirect: 'follow',
      signal: timeout,
      headers: {
        Range: `bytes=0-${PYPI_SPEED_SAMPLE_BYTES - 1}`,
        'User-Agent': 'WisprStudio-setup',
      },
    });
    if ((response.status !== 206 && response.status !== 200) || !response.body) return null;
    const reader = response.body.getReader();
    let received = 0;
    try {
      while (received < PYPI_SPEED_SAMPLE_BYTES) {
        const { done, value } = await reader.read();
        if (done) break;
        received += value.byteLength;
      }
    } finally {
      await reader.cancel().catch(() => undefined);
    }
    return received >= PYPI_SPEED_SAMPLE_BYTES ? performance.now() - started : null;
  } catch {
    return null;
  }
};

export interface MirrorRace {
  mirror: string | null;
  originMs: number | null;
  mirrorMs: number | null;
}

/** Auto mode never races unsolicited third-party PyPI mirrors. */
export async function raceAutoPypiMirror(
  _lock: string,
  _signal: AbortSignal,
  _time: SampleTimer = timeSample,
): Promise<MirrorRace> {
  return { mirror: null, originMs: null, mirrorMs: null };
}

export function mirrorLockUrls(lock: string, mirror: string | null): string {
  if (!mirror) return lock;
  return lock.replace(new RegExp(`(\\burl = ")${escape(PYPI_FILES_ORIGIN)}`, 'g'), `$1${mirror}`);
}

export function normalizeLockHosts(lock: string): string {
  let result = lock;
  for (const mirror of KNOWN_MIRRORS) {
    result = result.replace(
      new RegExp(`(\\burl = ")${escape(mirror)}`, 'g'),
      `$1${PYPI_FILES_ORIGIN}`,
    );
  }
  return result;
}
