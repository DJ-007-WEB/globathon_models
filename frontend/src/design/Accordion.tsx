// Single-open accordion with a royal left rule on the open item (reference FAQ).
import { useId, useState } from "react";
import { Icon } from "./Icon";

export interface AccordionItem { question: string; answer: string }

export function Accordion({ items, defaultOpen = 0 }: { items: AccordionItem[]; defaultOpen?: number | null }) {
  const [open, setOpen] = useState<number | null>(defaultOpen);
  const id = useId();
  return (
    <div className="accordion">
      {items.map((item, index) => {
        const isOpen = open === index;
        return (
          <div className={`accordion-item ${isOpen ? "is-open" : ""}`} key={item.question}>
            <h3>
              <button type="button" aria-expanded={isOpen} aria-controls={`${id}-${index}`} id={`${id}-h-${index}`}
                onClick={() => setOpen(isOpen ? null : index)}>
                <span>{item.question}</span>
                <Icon name={isOpen ? "x" : "plus"} size={16} />
              </button>
            </h3>
            <div className="accordion-panel" id={`${id}-${index}`} role="region" aria-labelledby={`${id}-h-${index}`} hidden={!isOpen}>
              <p>{item.answer}</p>
            </div>
          </div>
        );
      })}
    </div>
  );
}
