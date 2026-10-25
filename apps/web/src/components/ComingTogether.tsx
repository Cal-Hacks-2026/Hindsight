// Placeholder for a page that's in the nav but not built yet.
import { Masthead } from "./Paper";

export function ComingTogether({
  title,
  sketch,
}: {
  title: string;
  sketch: "books" | "cap" | "pencil" | "compass";
}) {
  return (
    <div className="coming-together">
      <Masthead sketch={sketch}>{title}</Masthead>
      <section className="section">
        <p className="coming-together-note">Coming together.</p>
      </section>
    </div>
  );
}
