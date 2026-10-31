import { Link, useParams } from "react-router-dom";
import { Icon } from "../../design/Icon";
import { RESOURCES } from "../../content/site";
import { FaqSection, PageHero } from "../sections";

export function Resources() {
  const { slug } = useParams();
  const doc = RESOURCES.find((item) => item.slug === slug) ?? RESOURCES[0];
  return (
    <>
      <PageHero image="/images/dusk-field.jpg" eyebrow="Resources" title="How SolarSleuth reads your data."
        body="What to export, how the pipeline works and where its limits are." />
      <section className="section">
        <div className="container docs">
          <nav className="doc-tabs" aria-label="Documents">
            {RESOURCES.map((item) => (
              <Link key={item.slug} to={`/resources/${item.slug}`} className={`doc-tab ${item.slug === doc.slug ? "active" : ""}`}
                aria-current={item.slug === doc.slug ? "page" : undefined}>
                <Icon name={item.icon} />{item.title}{item.slug === doc.slug && <Icon name="arrow-right" className="arrow" />}
              </Link>
            ))}
          </nav>
          <article className="doc-card" key={doc.slug}>
            <span className="eyebrow">Guide</span>
            <h2>{doc.title}</h2>
            <ul>{doc.items.map((item) => <li key={item}>{item}</li>)}</ul>
          </article>
        </div>
      </section>
      <FaqSection />
    </>
  );
}
