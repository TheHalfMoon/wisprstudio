import { useTranslation } from 'react-i18next';
import { Code2Icon } from 'lucide-react';
import { getBridge } from '@/components/bridge';
import { runRendererTask } from '@/lib/global-error-recovery';
import { REPO_URL } from '@shared/utils/contactLinks';
import { Tooltip, TooltipTrigger, TooltipContent } from '@/components/ui/tooltip';

/**
 * Static AGPL-3.0-only source repository link — zero live GitHub API polling.
 */
export function GithubStar() {
  const { t } = useTranslation();
  return (
    <Tooltip>
      <TooltipTrigger
        render={
          <a
            href={REPO_URL}
            target="_blank"
            rel="noopener noreferrer"
            aria-label={t('support.star_github')}
            className="github-star-shortcut app-no-drag inline-flex shrink-0 items-center text-xs font-medium focus-visible:outline-2 focus-visible:outline-ring"
            onClick={(event) => {
              const bridge = getBridge();
              if (!bridge) return;
              event.preventDefault();
              runRendererTask('Open source repository', () => bridge.files.openExternal(REPO_URL));
            }}
          />
        }
      >
        <span className="github-star-label">
          <Code2Icon aria-hidden="true" className="size-3.5" />
          <span>AGPLv3</span>
        </span>
      </TooltipTrigger>
      <TooltipContent surface="theme" side="bottom">
        {REPO_URL}
      </TooltipContent>
    </Tooltip>
  );
}
