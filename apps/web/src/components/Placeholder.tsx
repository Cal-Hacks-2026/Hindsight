export function Placeholder({ title, purpose, phase }: { title: string; purpose: string; phase: string }) {
  return (
    <section>
      <h1>{title}</h1>
      <p className="muted">{purpose}</p>
      <p className="card muted">Coming in {phase}.</p>
    </section>
  );
}
