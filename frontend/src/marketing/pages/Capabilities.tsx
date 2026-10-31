import { useEffect } from "react";
import { useLocation } from "react-router-dom";
import { Icon } from "../../design/Icon";
import { Reveal } from "../../design/Reveal";
import { CAPABILITIES } from "../../content/site";
import { CtaSection, PageHero, PipelineExplorer } from "../sections";

export function Capabilities() {
  const { hash } = useLocation();
  useEffect(() => {
    if (hash) window.setTimeout(() => document.getElementById(hash.slice(1))?.scrollIntoView({ behavior: "smooth" }), 120);
  }, [hash]);
  return (
    <>
      <PageHero image="/images/pylon-dusk.jpg" eyebrow="Capabilities" title="Everything between an export and an answer."
        body="Six capabilities, run in order on every upload. Each one states its inputs, its outputs and what happens when data is missing." />
      <section className="section">
        <div className="container">
          {CAPABILITIES.map((cap, index) => (
            <div className={`cap-row ${index % 2 ? "flip" : ""}`} id={cap.slug} key={cap.slug}>
              <Reveal className="rounded-photo"><img src={cap.image} alt="" loading="lazy" /></Reveal>
              <Reveal delay={100}>
                <span className="icon-tile"><Icon name={cap.icon} /></span>
                <h2>{cap.title}</h2>
                <p>{cap.body}</p>
                <ul className="check-list">{cap.bullets.map((bullet) => <li key={bullet}><Icon name="check" size={16} />{bullet}</li>)}</ul>
              </Reveal>
            </div>
          ))}
        </div>
      </section>
      <PipelineExplorer />
      <CtaSection />
    </>
  );
}
