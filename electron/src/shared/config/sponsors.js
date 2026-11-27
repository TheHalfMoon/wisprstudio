// WisprStudio sponsor configuration — empty by policy (no third-party ad/sponsor slots).

import { GITHUB_SPONSORS_URL, KOFI_URL } from '../utils/donateLinks';

const REPO = 'https://github.com/TheHalfMoon/wisprstudio';

/**
 * @type {{ name: string, logoUrl: string, url: string, tier: string }[]}
 */
export const SPONSORS = [];

/**
 * @type {string[]}
 */
export const SPONSOR_TIERS = ['strategic', 'company', 'development', 'community', 'supporter'];

export const SPONSOR_CONTACT = {
  githubIssue: `${REPO}/issues`,
  githubSponsors: GITHUB_SPONSORS_URL,
  kofi: KOFI_URL,
  docsUrl: `${REPO}/blob/main/SPONSORS.md`,
};
