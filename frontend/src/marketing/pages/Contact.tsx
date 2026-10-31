import { Link } from "react-router-dom";
import { Icon } from "../../design/Icon";
import { PageHero } from "../sections";
import { useOpenWorkspace } from "../MarketingLayout";

export function Contact() {
  const openWorkspace = useOpenWorkspace();
  return (
    <>
      <PageHero className="has-cards" image="/images/switchgear-room.jpg" eyebrow="Contact" title="Talk to the project."
        body="The fastest way to evaluate SolarSleuth is to run it on your own export." />
      <section className="section" style={{ paddingTop: 0 }}>
        <div className="container">
          <div className="contact-cards">
            <article className="contact-card">
              <span className="chip"><Icon name="upload" /></span><h3>Try it on your data</h3>
              <p>Create a workspace and upload a CSV or XLSX export.</p>
              <button type="button" className="text-link" style={{ border: 0, background: "none", padding: 0 }} onClick={() => openWorkspace("signup")}>Create a workspace <Icon name="arrow-right" /></button>
            </article>
            <article className="contact-card">
              <span className="chip"><Icon name="book" /></span><h3>Read the method</h3>
              <p>Data requirements, pipeline stages and documented limits.</p>
              <Link className="text-link" to="/resources">Open resources <Icon name="arrow-right" /></Link>
            </article>
            <article className="contact-card">
              <span className="chip"><Icon name="link" /></span><h3>Source and issues</h3>
              <p>Report a problem or review the code in the project repository.</p>
              <a className="text-link" href="https://github.com/dj-007-web/globathon_models" target="_blank" rel="noreferrer">Open repository <Icon name="arrow-up-right" /></a>
            </article>
          </div>
          <p className="muted" style={{ textAlign: "center", marginTop: 40, fontSize: 14 }}>This website does not collect enquiries through a form.</p>
        </div>
      </section>
    </>
  );
}

export function NotFound() {
  return (
    <section className="section" style={{ paddingTop: 160 }}>
      <div className="container narrow closing">
        <span className="eyebrow">404</span>
        <h1 className="display-2">This page does not exist.</h1>
        <p className="lead">The link may be outdated.</p>
        <Link className="btn btn-royal" to="/">Back to home</Link>
      </div>
    </section>
  );
}
