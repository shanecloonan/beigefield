import type { CatalogCell, PublicCatalog } from "@/lib/supabase/catalog";
import { formatTimestamp, rowCountLabel } from "@/lib/supabase/format";

function displayCell(column: string, value: CatalogCell): string {
  if (value === null) return "—";
  if (typeof value === "boolean") return value ? "true" : "false";
  if (typeof value === "number") return String(value);
  if (column.endsWith("_at") || /^\d{4}-\d{2}-\d{2}T/.test(value)) return formatTimestamp(value);
  return value;
}

export function CatalogList({ catalog }: { catalog: PublicCatalog }) {
  if (!catalog.configured) {
    return (
      <p className="ton-section-copy">
        This environment has no database URL or password, so table names are not
        listed from Postgres. The ping test below still reads{" "}
        <span className="ton-mono">ping_tests</span> with the public API key.
      </p>
    );
  }

  if (catalog.error) {
    return <p className="ton-section-copy">{catalog.error}</p>;
  }

  if (catalog.tables.length === 0) {
    return <p className="ton-section-copy">No tables in the public schema.</p>;
  }

  return (
    <div className="sb-stack">
      {catalog.tables.map((table, index) => (
        <article key={`${table.name}-${index}`} className="sb-table-block">
          <h3>{table.name}</h3>
          <p className="ton-hint">
            {table.rowCount === null ? "Row count unavailable" : rowCountLabel(table.rowCount)}
            {table.error ? ` · ${table.error}` : ""}
          </p>
          {table.sample.length > 0 && table.columns.length > 0 ? (
            <div className="sb-scroll">
              <table className="sb-table">
                <caption>
                  {table.sample.length === 1
                    ? "Latest row"
                    : `Latest ${table.sample.length} rows`}
                </caption>
                <thead>
                  <tr>
                    {table.columns.map((column) => (
                      <th key={column} scope="col">
                        {column}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {table.sample.map((row, index) => (
                    <tr key={`${table.name}-${index}`}>
                      {row.map((value, cellIndex) => (
                        <td key={table.columns[cellIndex] ?? cellIndex}>
                          {displayCell(table.columns[cellIndex] ?? "", value)}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : table.error ? null : (
            <p className="ton-hint">No rows yet.</p>
          )}
        </article>
      ))}
    </div>
  );
}
