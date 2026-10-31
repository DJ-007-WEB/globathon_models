import { Link } from "react-router-dom";
import { Icon } from "../../design/Icon";
import { Reveal } from "../../design/Reveal";
import { AUDIENCES, CAPABILITIES, FACTS, PRINCIPLES } from "../../content/site";
import { CtaSection, FaqSection, HeroWaterfallCard, LimitsMarquee, PipelineExplorer } from "../sections";
import { useOpenWorkspace } from "../MarketingLayout";

export function Home() {
  const openWorkspace = useOpenWorkspace();
  return (
    <>
      <section className="hero">
        <div className="hero-media"><img src="/images/hero-aerial.jpg" alt="" /></div>
        <div className="container">
          <div className="hero-in">
            <span className="eyebrow eyebrow-rule">Solar performance intelligence</span>
            <h1 className="display-1">Know why your plant delivered <em>less than forecast</em>.</h1>
            <p className="lead">Upload a monitoring export. SolarSleuth validates it, models expected energy, splits the gap into weather and plant effects and flags unusual intervals — then a local AI explains the result.</p>
            <div className="hero-actions">
              <button type="button" className="btn btn-lime" onClick={() => openWorkspace("signup")}>Create a workspace <Icon name="arrow-right" className="arrow" /></button>
              <Link className="btn btn-ghost-light" to="/demo">See the product demo</Link>
            </div>
            <p className="hero-meta">CSV or XLSX · deterministic numbers · hypotheses, not verdicts</p>
          </div>
          <HeroWaterfallCard />
        </div>
      </section>

      <section className="section">
        <div className="container">
          <div className="problem-grid">
            <Reveal>
              <span className="eyebrow eyebrow-rule">The operational problem</span>
              <h2 className="h2">A shortfall number is not an explanation.</h2>
            </Reveal>
            <Reveal delay={100}><p className="lead">Monitoring portals show that a plant under-delivered. They rarely show how much was weather, how much was the plant, and which intervals deserve a site visit. SolarSleuth reconciles the gap from the data you already export, and says plainly what it cannot know.</p></Reveal>
          </div>
          <Reveal className="stat-strip">
            {FACTS.map((fact) => (
              <div className="stat" key={fact.label}>
                <small>{fact.label}</small><strong>{fact.value}</strong><p>{fact.body}</p><span className="bar" />
              </div>
            ))}
          </Reveal>
        </div>
      </section>

      <PipelineExplorer />

      <section className="section section-mist">
        <div className="container">
          <div className="section-head">
            <Reveal><span className="eyebrow eyebrow-rule">Capabilities</span><h2 className="h2">Six parts of one report.</h2></Reveal>
            <Link className="text-link" to="/capabilities">All capabilities <Icon name="arrow-right" /></Link>
          </div>
          <div className="cap-grid">
            {CAPABILITIES.map((cap, index) => (
              <Reveal key={cap.slug} delay={index * 60} className="cap-card">
                <div className="cap-photo"><img src={cap.image} alt="" loading="lazy" /></div>
                <div className="cap-inner">
                  <div className="cap-top"><span className="icon-tile"><Icon name={cap.icon} /></span><small>0{index + 1}</small></div>
                  <h3>{cap.title}</h3>
                  <p>{cap.body}</p>
                  <ul>{cap.bullets.map((bullet) => <li key={bullet}>{bullet}</li>)}</ul>
                  <div className="bar"><i /></div>
                  <Link className="stretch" to={`/capabilities#${cap.slug}`} aria-label={`Read about ${cap.title}`} />
                </div>
              </Reveal>
            ))}
          </div>
        </div>
      </section>

      <section className="photo-section section">
        <img src="/images/dusk-field.jpg" alt="" loading="lazy" />
        <div className="container">
          <Reveal>
            <span className="eyebrow eyebrow-rule">Principles</span>
            <h2 className="h2">Built to be checked, not trusted blindly.</h2>
            <p className="lead">Three rules shape every screen and every sentence the product produces.</p>
          </Reveal>
          <div className="principle-grid">
            {PRINCIPLES.map((item, index) => (
              <Reveal key={item.title} delay={index * 100} className="principle">
                <small>0{index + 1}</small><h3>{item.title}</h3><span className="bar" /><p>{item.body}</p>
              </Reveal>
            ))}
          </div>
        </div>
      </section>

      <section className="section">
        <div className="container audience">
          <Reveal className="rounded-photo"><img src="/images/pv-topdown.jpg" alt="Aerial view of solar panel rows" loading="lazy" /></Reveal>
          <Reveal delay={120}>
            <span className="eyebrow eyebrow-rule">Who it is for</span>
            <h2 className="h2" style={{ marginTop: 12 }}>One report, read four ways.</h2>
            <div className="audience-rows">
              {AUDIENCES.map((item) => <div className="audience-row" key={item.title}><b>{item.title}</b><p>{item.body}</p></div>)}
            </div>
          </Reveal>
        </div>
      </section>

      <FaqSection />
      <LimitsMarquee />
      <CtaSection />
    </>
  );
}
