import Link from "next/link";

export default function Home() {
  return (
    <div className="page">
      <div className="frame" aria-hidden="true">
        <span className="corner corner-tl" />
        <span className="corner corner-tr" />
        <span className="corner corner-bl" />
        <span className="corner corner-br" />
      </div>
      <main className="lockup">
        <h1>Beigefield</h1>
        <span className="rule" aria-hidden="true" />
        <p>Blockchain Research</p>
        <nav className="lockup-nav" aria-label="Tools">
          <Link href="/test">Scanner</Link>
          <Link href="/blend">Blend</Link>
        </nav>
      </main>
    </div>
  );
}
