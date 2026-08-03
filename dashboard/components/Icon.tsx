// Icon.tsx — renders a Font Awesome 5 Free Solid glyph from its hex codepoint
// via the bundled font (public/fonts/fa-solid-900.woff2, wired up in
// milford-system.css's `.fa` class). Using String.fromCharCode(...) instead of
// pasting the raw private-use glyph keeps this file plain ASCII and diff/edit
// friendly.
export function Icon({ code, className = "" }: { code: string; className?: string }) {
  return (
    <i className={`fa ${className}`.trim()} aria-hidden="true">
      {String.fromCharCode(parseInt(code, 16))}
    </i>
  );
}
