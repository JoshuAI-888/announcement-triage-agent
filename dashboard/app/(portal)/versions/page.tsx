import Link from "next/link";
import { Icon } from "@/components/Icon";
import { listBriefVersions } from "@/lib/dataSource";
import { KIND_LABEL } from "@/lib/flags";

export const dynamic = "force-dynamic";

export default async function VersionsPage() {
  const versions = await listBriefVersions(30);

  return (
    <section>
      <div className="page-head">
        <div>
          <p className="eyebrow">Draft versions</p>
          <h1>Brief archive</h1>
          <p>The last {versions.length || ""} rendered briefs from out/briefs/*.email.html, newest first (CONTRACTS.md §4).</p>
        </div>
      </div>

      {versions.length === 0 ? (
        <div className="card card-pad empty">
          <p>No out/briefs/*.email.html found in this checkout yet.</p>
        </div>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>File</th>
                <th>Date</th>
                <th>Kind</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {versions.map((v) => (
                <tr key={v.name}>
                  <td className="mono small">{v.name}</td>
                  <td>{v.date}</td>
                  <td>
                    <span className={`badge ${v.kind === "intraday" ? "orange" : v.kind === "backfill" ? "purple" : ""}`}>
                      {KIND_LABEL[v.kind] ?? v.kind}
                    </span>
                  </td>
                  <td>
                    <Link className="btn secondary" href={`/versions/${encodeURIComponent(v.name)}`}>
                      <Icon code="f06e" /> View
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
