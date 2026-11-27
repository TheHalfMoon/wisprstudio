// @vitest-environment node
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  AUTO_PYPI_MIRROR,
  PYPI_FILES_ORIGIN,
  PYPI_SPEED_SAMPLE_BYTES,
  mirrorLockUrls,
  normalizeLockHosts,
  pypiFilesHost,
  pypiFilesMirror,
  raceAutoPypiMirror,
  speedSampleUrl,
  timeSample,
} from './pypi-mirror';

const LOCK = readFileSync(join(__dirname, '..', '..', '..', 'uv.lock'), 'utf8');

describe('PyPI canonical-only policy (no unsolicited third-party mirrors)', () => {
  it('never maps any region to unsolicited third-party mirrors', () => {
    expect(AUTO_PYPI_MIRROR).toBeNull();
    for (const region of ['auto', 'global', 'china', 'russia', 'restricted']) {
      expect(pypiFilesMirror(region)).toBeNull();
      expect(pypiFilesHost(region)).toBe('files.pythonhosted.org');
    }
  });

  it('leaves the lock byte-identical without a mirror', () => {
    expect(mirrorLockUrls(LOCK, null)).toBe(LOCK);
    expect(mirrorLockUrls(LOCK, pypiFilesMirror('china'))).toBe(LOCK);
    expect(normalizeLockHosts(LOCK)).toBe(LOCK);
  });
});

describe('PyPI speed sample helpers', () => {
  afterEach(() => vi.unstubAllGlobals());
  const signal = new AbortController().signal;
  const sample = speedSampleUrl(LOCK)!;

  it('samples one locked PyPI wheel large enough to time', () => {
    expect(sample.startsWith(PYPI_FILES_ORIGIN)).toBe(true);
    expect(sample.endsWith('.whl')).toBe(true);
    expect(speedSampleUrl('')).toBeNull();
  });

  it('never races unsolicited mirrors in auto mode', async () => {
    const time = vi.fn(async () => 100);
    expect(await raceAutoPypiMirror(LOCK, signal, time)).toEqual({
      mirror: null,
      originMs: null,
      mirrorMs: null,
    });
    expect(time).not.toHaveBeenCalled();
  });

  it('times one ranged GET with a WisprStudio-setup User-Agent and fails on short responses', async () => {
    const fetch = vi.fn(
      async () => new Response(new Uint8Array(PYPI_SPEED_SAMPLE_BYTES), { status: 206 }),
    );
    vi.stubGlobal('fetch', fetch);
    expect(await timeSample(sample, signal)).toEqual(expect.any(Number));
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(fetch.mock.calls[0]).toEqual([
      sample,
      expect.objectContaining({
        headers: expect.objectContaining({
          Range: `bytes=0-${PYPI_SPEED_SAMPLE_BYTES - 1}`,
          'User-Agent': 'WisprStudio-setup',
        }),
      }),
    ]);
    fetch.mockImplementationOnce(async () => new Response(new Uint8Array(10), { status: 206 }));
    expect(await timeSample(sample, signal)).toBeNull();
  });
});
