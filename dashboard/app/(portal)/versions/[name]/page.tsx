import Link from "next/link";
import { notFound } from "next/navigation";
import { Icon } from "@/components/Icon";
import { getBriefHtml } from "@/lib/dataSource";

export const dynamic = "force-dynamic";

export default async function VersionDetailPage({ params }: { params: Promise<{ name: string }> }) {
  const { name } = await params;
  const decoded = decodeURIComponent(name);
  const html = await getBriefHtml(decoded);
  if (html === null) notFound();

  return (
    <section>
      <div className="page-head">
        <div>
          <p className="eyebrow">Draft versions</p>
          <h1>{decoded}</h1>
          <p>Rendered brief, exactly as archived (self-contained inline-CSS HTML).</p>
        </div>
        <div className="actions">
          <Link className="btn secondary" href="/versions">
            <Icon code="f060" /> Back to list
          </Link>
          <a className="btn" href={`/api/versions/${encodeURIComponent(decoded)}`} target="_blank" rel="noreferrer">
            <Icon code="f08e" /> Open raw
          </a>
        </div>
      </div>
      <div className="brief-frame-wrap">
        <iframe className="brief-frame" src={`/api/versions/${encodeURIComponent(decoded)}`} title={decoded} />
      </div>
    </section>
  );
}
