import { Code2Icon, ShieldCheckIcon } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { WorkspaceHeader } from '@/components/app-shell/workspace-header';
import { ExternalLink } from '@/components/external-link';
import { REPO_URL } from '@shared/utils/contactLinks';
import './pro-page.css';

/**
 * WisprStudio Open-Source License & Source Code Offer (`AGPL-3.0-only`).
 * Replaces commercial Pro/Cloud upsell plans with transparent open-source terms.
 */
export function ProPage() {
  const { t } = useTranslation();
  return (
    <div className="pro-page">
      <WorkspaceHeader>
        <h1 className="text-sm font-medium">{t('app.name')}</h1>
      </WorkspaceHeader>
      <div className="pro-page-scroll">
        <main className="pro-page-content">
          <section className="pro-pricing" id="open-source-offer">
            <div className="pro-section-head">
              <div className="mb-3 inline-flex items-center gap-2 text-primary">
                <ShieldCheckIcon className="size-5" aria-hidden="true" />
                <span className="text-xs font-semibold uppercase tracking-wider">
                  {t('pro.license_badge')}
                </span>
              </div>
              <h2>{t('pro.open_source_heading')}</h2>
              <p>{t('pro.open_source_body')}</p>
              <div className="mt-4 flex flex-wrap gap-3">
                <ExternalLink href={REPO_URL}>
                  <Code2Icon className="size-4" aria-hidden="true" />
                  {t('pro.source_code_cta', { url: REPO_URL })}
                </ExternalLink>
              </div>
            </div>
          </section>
        </main>
      </div>
    </div>
  );
}
