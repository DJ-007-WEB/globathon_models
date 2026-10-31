import { Link } from "react-router-dom";
import { Icon } from "../../design/Icon";
import { Reveal } from "../../design/Reveal";
import { CtaSection, HeroWaterfallCard, PageHero } from "../sections";

const SHOTS = [
  { icon: "report" as const, title: "Normal operation", body: "Scenario 001 — a clean dataset where weather explains almost the whole gap.", to: "/preview/reports/preview-001" },
  { icon: "alert" as const, title: "Inverter outage", body: "Scenario 002 — one inverter drops out; anomalies and hypotheses are raised.", to: "/preview/reports/preview-002" },
  { icon: "pulse" as const, title: "Gradual derating", body: "Scenario 003 — a sustained shortfall attributed to the plant effect.", to: "/preview/reports/preview-003" },
];

export function Demo() {
  return (
    <>
      <PageHero image="/images/pv-landscape.jpg" eyebrow="Product demo" title="Explore a workspace built from synthetic data."
        body="Three generated scenarios were processed by the real ML pipeline. The numbers are genuine pipeline output; the plant is not real." />
      <section className="section">
        <div className="container">
          <div className="section-head">
            <Reveal><span className="synthetic-tag"><Icon name="flask" size={14} />Synthetic data</span><h2 className="h2">Three scenarios, three reports.</h2></Reveal>
            <Link className="btn btn-royal" to="/preview">Open synthetic workspace <Icon name="arrow-right" className="arrow" /></Link>
          </div>
          <div className="demo-panel">
            {SHOTS.map((shot, index) => (
              <Reveal key={shot.title} delay={index * 80} className="demo-shot">
                <span className="icon-tile"><Icon name={shot.icon} /></span>
                <h3>{shot.title}</h3><p>{shot.body}</p>
                <Link className="text-link" to={shot.to} style={{ marginTop: 14 }}>Open report <Icon name="arrow-right" /></Link>
              </Reveal>
            ))}
          </div>
        </div>
      </section>
      <section className="section section-mist">
        <div className="container audience">
          <Reveal>
            <span className="eyebrow eyebrow-rule">Waterfall</span>
            <h2 className="h2" style={{ marginTop: 12 }}>Where the energy went.</h2>
            <p className="lead" style={{ marginTop: 12 }}>The synthetic preview has no AI narrative. Create a workspace to see the local model explain your own report.</p>
          </Reveal>
          <div className="demo-dark"><HeroWaterfallCard /></div>
        </div>
      </section>
      <CtaSection />
    </>
  );
}
