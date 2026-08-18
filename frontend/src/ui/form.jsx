/* Form layout primitives.
 *
 * Written for the five enrichment/config screens, which were five one-off
 * implementations of the same page: every value in a <textarea> regardless of
 * whether it held a name or an essay, and every field inside its own bordered
 * card, so the page read as card / card / card with no hierarchy in it.
 *
 * These are the shared parts, so the five pages look and behave identically
 * rather than resembling each other:
 *
 *   <Section>    a titled group with a rule above it — replaces the per-item card
 *   <FieldGrid>  two columns on desktop, one on narrow, `wide` to span
 *   <Field>      label + optional hint + control
 *   <Text>       a single-line input, for values that are single-line
 *   <Area>       a fixed-height textarea that scrolls its own overflow
 *   <StickyBar>  the save row, pinned to the bottom of a long page
 */

export function Section({ title, hint, actions, children, className = "", first = false }) {
  return (
    <section className={`fs ${first ? "first" : ""} ${className}`}>
      {(title || actions) && (
        <header className="fs-head">
          <div className="fs-heading">
            {title && <h2>{title}</h2>}
            {hint && <p>{hint}</p>}
          </div>
          {actions && <div className="fs-acts">{actions}</div>}
        </header>
      )}
      {children}
    </section>
  );
}

export function FieldGrid({ children, className = "" }) {
  return <div className={`fgrid ${className}`}>{children}</div>;
}

export function Field({ label, hint, wide = false, htmlFor, children, className = "" }) {
  return (
    <div className={`ffield ${wide ? "wide" : ""} ${className}`}>
      {label && <label htmlFor={htmlFor}>{label}{hint && <span className="fhint">{hint}</span>}</label>}
      {children}
    </div>
  );
}

export const Text = (props) => <input type="text" {...props} />;
export const Num = (props) => <input type="number" {...props} />;
export const Url = (props) => <input type="url" inputMode="url" {...props} />;

/** How tall a field is, by how much writing it actually expects.
 *
 *  A shared scale rather than a number per call site: "this is a medium field"
 *  survives a redesign, `rows={6}` does not, and three tiers keep the forms
 *  looking like one product instead of forty independent guesses.
 *
 *    sm — a sentence or two, or a short list. Notes, fallbacks, one-line rules.
 *    md — a paragraph you expect to read back. Guidance, briefs, descriptions.
 *    lg — long-form. An ICP definition, global rules, a transcript, a JSON blob.
 */
const SIZE_ROWS = { sm: 3, md: 6, lg: 12 };

/** A textarea of fixed height that scrolls its own overflow.
 *
 *  Height comes from `size` (or an explicit `rows` where a field genuinely does
 *  not fit the scale). It is the height, full stop — not a starting size and
 *  not a floor. The box never grows: past that many lines the content scrolls
 *  inside it. That keeps a form's layout still while it is being filled in,
 *  which is the whole point — a field that pushes everything below it down as
 *  you type moves the buttons you are aiming at.
 *
 *  No drag handle either (`resize: none`, set in styles.css alongside the
 *  hairline scrollbar), so the height a screen is designed at is the height it
 *  keeps. */
export function Area({ size = "sm", rows, className = "", ...rest }) {
  return <textarea rows={rows ?? SIZE_ROWS[size] ?? SIZE_ROWS.sm} className={`fta ${className}`} {...rest} />;
}

/** Page-level save bar. Sticks to the bottom so a long form never makes you
 *  scroll back to the top to commit what you just typed. */
export function StickyBar({ children, note }) {
  return (
    <div className="fbar">
      {note && <span className="fbar-note">{note}</span>}
      <span className="fbar-spacer" />
      {children}
    </div>
  );
}
