import Link from "next/link";

export default function SupabaseLoading() {
  return (
    <div className="page">
      <div className="frame" aria-hidden="true">
        <span className="corner corner-tl" />
        <span className="corner corner-tr" />
        <span className="corner corner-bl" />
        <span className="corner corner-br" />
      </div>
      <main className="ton-main">
        <Link className="ton-mark" href="/">
          Beigefield
        </Link>
        <p className="ton-kicker">Database</p>
        <h1>Supabase</h1>
        <p className="ton-lede">Reading the project.</p>
      </main>
    </div>
  );
}
