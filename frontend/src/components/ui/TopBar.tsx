import Link from "next/link";
import { Fragment } from "react";
import Icon from "./Icon";
import { buttonClass, cx } from "./kit";

export interface Crumb { label: string; href?: string }

/** The bar at the top of every signed-in page: breadcrumb on the left, page actions on the right. */
export default function TopBar({ crumbs, children, className }: {
  crumbs: Crumb[];
  children?: React.ReactNode;
  className?: string;
}) {
  return (
    <header className={cx(
      "flex flex-wrap items-center justify-between gap-3 px-4 sm:px-8 py-[14px] border-b border-border bg-surface",
      className,
    )}>
      <nav aria-label="Breadcrumb" className="flex items-center gap-2 min-w-0 text-[13.5px] text-ink-3">
        {crumbs.map((c, i) => {
          const last = i === crumbs.length - 1;
          return (
            <Fragment key={`${c.label}-${i}`}>
              {i > 0 && <span aria-hidden="true">/</span>}
              {last ? (
                <span aria-current="page" className="text-ink font-medium truncate">{c.label}</span>
              ) : c.href ? (
                <Link href={c.href} className="text-ink-3 hover:text-ink shrink-0">{c.label}</Link>
              ) : (
                <span className="shrink-0">{c.label}</span>
              )}
            </Fragment>
          );
        })}
      </nav>
      {children && <div className="flex flex-wrap items-center gap-2 min-w-0">{children}</div>}
    </header>
  );
}

/** The global action: open the feed with the paste-a-link field focused. */
export function AnalyseLinkButton() {
  return (
    <Link href="/jobs?paste=1" className={buttonClass("secondary", "top")}>
      <Icon name="link" size={16} />
      Analyse a job link
    </Link>
  );
}

/** Page body: the content column under the top bar. */
export function Page({ children, wide, className }: { children: React.ReactNode; wide?: "feed" | "job"; className?: string }) {
  return (
    <div className={cx(
      "w-full box-border px-4 sm:px-8 pt-6 sm:pt-7 pb-14 flex flex-col",
      wide === "feed" ? "max-w-[1320px]" : wide === "job" ? "max-w-[1280px]" : "max-w-[1240px]",
      className,
    )}>
      {children}
    </div>
  );
}
