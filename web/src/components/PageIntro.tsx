import type { ReactNode } from "react";

interface PageIntroProps {
  eyebrow: string;
  title: string;
  lede: string;
  children?: ReactNode;
}

/** Consistent editorial header for each view: an eyebrow, a large title, and a lede. */
export function PageIntro({ eyebrow, title, lede, children }: PageIntroProps) {
  return (
    <header className="page-intro">
      <p className="eyebrow">{eyebrow}</p>
      <h1 className="page-title">{title}</h1>
      <p className="lede">{lede}</p>
      {children}
    </header>
  );
}
