// SolarSleuth mark: lime plate with a magnifier over a PV-cell grid. Recreated in SVG.
export function LogoMark({ size = 30 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden="true" className="logo-mark">
      <rect width="32" height="32" rx="8" fill="var(--lime-400)" />
      <circle cx="14" cy="14" r="7" fill="none" stroke="#0b150f" strokeWidth="2.6" />
      <path d="M11 12.2h6M11 15.8h6M14 9.5v9" stroke="#0b150f" strokeWidth="1.4" strokeLinecap="round" />
      <path d="M19.2 19.2 24.5 24.5" stroke="#0b150f" strokeWidth="3" strokeLinecap="round" />
    </svg>
  );
}

export function Logo({ tone = "dark", size = 30 }: { tone?: "dark" | "light"; size?: number }) {
  return (
    <span className={`logo logo-${tone}`}>
      <LogoMark size={size} />
      <span className="logo-word">Solar<span>Sleuth</span></span>
    </span>
  );
}
