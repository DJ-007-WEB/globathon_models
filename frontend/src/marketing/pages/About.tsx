import { Reveal } from "../../design/Reveal";
import { AUDIENCES } from "../../content/site";
import { CtaSection, LimitsMarquee, PageHero } from "../sections";

export function About() {
  return (
    <>
      <PageHero image="/images/hero-aerial.jpg" eyebrow="About" title="Performance analysis that shows its working."
        body="SolarSleuth exists because a shortfall number alone does not tell an operator what to check next." />
      <section className="section">
        <div className="container problem-grid">
          <Reveal><span className="eyebrow eyebrow-rule">Why it matters</span><h2 className="h2">Every kilowatt-hour has a reason.</h2></Reveal>
          <Reveal delay={100}>
            <p className="lead">Solar plants routinely deliver less than forecast. Part of the gap is weather and nobody can fix it; part is the plant, and some of that may be recoverable. Telling the two apart usually takes an analyst, a spreadsheet and a day.</p>
            <p className="lead" style={{ marginTop: 16 }}>SolarSleuth runs that reasoning deterministically on the export you already have, keeps every number traceable, and uses a local language model only to explain the result.</p>
          </Reveal>
        </div>
      </section>
      <section className="section section-mist">
        <div className="container audience">
          <Reveal className="rounded-photo"><img src="/images/pv-landscape.jpg" alt="" loading="lazy" /></Reveal>
          <Reveal delay={100}>
            <span className="eyebrow eyebrow-rule">Who we build for</span>
            <div className="audience-rows">{AUDIENCES.map((item) => <div className="audience-row" key={item.title}><b>{item.title}</b><p>{item.body}</p></div>)}</div>
          </Reveal>
        </div>
      </section>
      <LimitsMarquee />
      <CtaSection />
    </>
  );
}
