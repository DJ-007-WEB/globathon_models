import { Icon } from "../../design/Icon";
import { Reveal } from "../../design/Reveal";
import { CAN, CANNOT, DATA_HANDLING, PRINCIPLES } from "../../content/site";
import { CtaSection, LimitsMarquee, PageHero } from "../sections";

export function Trust() {
  return (
    <>
      <PageHero image="/images/pv-topdown.jpg" eyebrow="Trust & method" title="Numbers you can trace. Claims you can check."
        body="SolarSleuth separates measured facts, rule-based hypotheses and AI narrative — and shows which is which." />
      <section className="section">
        <div className="container three-col">
          {PRINCIPLES.map((item, index) => (
            <Reveal key={item.title} delay={index * 100}><small>0{index + 1}</small><h3>{item.title}</h3><span className="bar" /><p>{item.body}</p></Reveal>
          ))}
        </div>
      </section>
      <section className="section section-mist">
        <div className="container">
          <Reveal><span className="eyebrow eyebrow-rule">Scope</span><h2 className="h2" style={{ marginTop: 12 }}>What it can and cannot do.</h2></Reveal>
          <div className="two-lists">
            <Reveal><h3 className="h3">It can</h3><ul className="check-list">{CAN.map((item) => <li key={item}><Icon name="check" size={16} />{item}</li>)}</ul></Reveal>
            <Reveal delay={100}><h3 className="h3">It cannot</h3><ul className="check-list cross">{CANNOT.map((item) => <li key={item}><Icon name="x" size={16} />{item}</li>)}</ul></Reveal>
          </div>
        </div>
      </section>
      <section className="section">
        <div className="container audience">
          <Reveal className="rounded-photo"><img src="/images/switchgear-room.jpg" alt="" loading="lazy" /></Reveal>
          <Reveal delay={100}>
            <span className="eyebrow eyebrow-rule">Data handling</span>
            <h2 className="h2" style={{ marginTop: 12 }}>What happens to your file.</h2>
            <div className="fact-rows">
              {DATA_HANDLING.map((row) => <div className="fact-row" key={row.title}><strong>{row.value}</strong><p><b>{row.title}</b> {row.body}</p></div>)}
            </div>
          </Reveal>
        </div>
      </section>
      <LimitsMarquee />
      <CtaSection />
    </>
  );
}
