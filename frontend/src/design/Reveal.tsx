// Fade-up on first view (IntersectionObserver, once). Reduced motion shows content immediately (CSS).
import { useEffect, useRef, useState, type CSSProperties, type ElementType, type ReactNode } from "react";

export function Reveal({ as: Tag = "div", delay = 0, className = "", children, ...rest }: {
  as?: ElementType; delay?: number; className?: string; children: ReactNode; [key: string]: unknown;
}) {
  const ref = useRef<HTMLElement>(null);
  const [visible, setVisible] = useState(false);
  useEffect(() => {
    const node = ref.current;
    if (!node) return;
    if (!("IntersectionObserver" in window)) { setVisible(true); return; }
    const observer = new IntersectionObserver((entries) => {
      if (entries.some((entry) => entry.isIntersecting)) { setVisible(true); observer.disconnect(); }
    }, { threshold: 0.15, rootMargin: "0px 0px -40px 0px" });
    observer.observe(node);
    return () => observer.disconnect();
  }, []);
  return (
    <Tag ref={ref} className={`reveal ${visible ? "is-visible" : ""} ${className}`} style={{ "--delay": `${delay}ms` } as CSSProperties} {...rest}>
      {children}
    </Tag>
  );
}
