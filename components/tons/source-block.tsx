import type { PathSource } from "@/lib/valdora-path";

export function SourceList({ sources }: { sources: readonly PathSource[] }) {
  return (
    <>
      {sources.map((source, index) => (
        <figure className="ton-source" key={`${source.file}-${index}`}>
          <figcaption className="ton-kicker">{source.file}</figcaption>
          <pre className="ton-code">
            <code>{source.code}</code>
          </pre>
        </figure>
      ))}
    </>
  );
}
