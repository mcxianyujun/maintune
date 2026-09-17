import type { CSSProperties, ReactNode } from "react";
import heroArt from "./luo-tianyi-maintainer-hero.webp";
import navSprite from "./luo-tianyi-nav-sprite.webp";
import { useI18n } from "../../i18n";

export type ThemeIconKind = "overview" | "github" | "repository" | "tasks" | "models" | "agents" | "sandbox" | "plugins" | "runs" | "settings";

const spritePosition: Record<ThemeIconKind, string> = {
  overview: "0% 0%", github: "25% 0%", repository: "50% 0%", tasks: "75% 0%", models: "100% 0%",
  agents: "0% 100%", sandbox: "25% 100%", plugins: "50% 100%", runs: "75% 100%", settings: "100% 100%",
};

export function BrandGlyph({ className = "" }: { className?: string }) {
  const { t } = useI18n();
  return <svg className={className} viewBox="0 0 48 48" role="img" aria-label={t("art.brand")}>
    <defs><linearGradient id="brandJade" x1="8" y1="7" x2="40" y2="42"><stop stopColor="#c6fff1"/><stop offset=".48" stopColor="#66ccff"/><stop offset="1" stopColor="#37a9dc"/></linearGradient></defs>
    <path d="M24 4.5c4.2 4.8 7.2 7.4 12.9 9.2-2.3 5.6-2.5 9.4 0 15-5.7 1.8-8.8 4.5-12.9 9.4-4.1-4.9-7.2-7.6-12.9-9.4 2.5-5.6 2.3-9.4 0-15C16.8 11.9 19.8 9.3 24 4.5Z" fill="url(#brandJade)" stroke="#218eb9" strokeWidth="1.7"/>
    <circle cx="24" cy="21.5" r="7.2" fill="#fff" fillOpacity=".9" stroke="#36a8d4" strokeWidth="1.4"/>
    <path d="M22 17v11.5c0 3.4-5.1 4-6.2 1-1-2.6 1.8-4.8 4.5-3.4v-8.4l8.8-1.9v8.5c0 3.4-5 4-6.2 1-1-2.6 1.8-4.8 4.5-3.4v-4.1Z" fill="#32a7d4"/>
    <path d="m34.5 34 2.1 2.1 4.1-4.7" fill="none" stroke="#ff80b3" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"/>
  </svg>;
}

export function NavMascotIcon({ kind }: { kind: ThemeIconKind }) {
  const { t } = useI18n();
  return <span className={`nav-mascot nav-mascot-${kind}`} style={{ "--mascot-image": `url(${navSprite})`, "--mascot-position": spritePosition[kind] } as CSSProperties} role="img" aria-label={t("art.nav", {kind})} />;
}

export function MascotScene({ variant = "dashboard", compact = false }: { variant?: "dashboard" | "welcome" | "ready" | "empty"; compact?: boolean }) {
  const { t } = useI18n();
  if (compact) {
    const position = variant === "ready" ? spritePosition.tasks : spritePosition.overview;
    return <span className="mascot-scene compact anime-chibi" style={{ "--mascot-image": `url(${navSprite})`, "--mascot-position": position } as CSSProperties} role="img" aria-label={t("art.chibi")}/>;
  }
  return <img className={`mascot-scene anime-hero anime-hero-${variant}`} src={heroArt} alt={t("art.hero")} />;
}

export function EmptyState({ title, children, action }: { title: string; children: ReactNode; action?: ReactNode }) {
  return <div className="empty themed-empty"><MascotScene variant="empty" compact/><div><h3>{title}</h3><p>{children}</p>{action}</div></div>;
}
