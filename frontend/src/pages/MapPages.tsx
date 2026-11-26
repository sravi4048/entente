import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { api, ApiError } from "../api";
import { Toast } from "../components/bits";
import MapView from "../components/MapView";
import { useLive } from "../live";
import { MapModel, powerColor, titleCase, useMap, type MapData } from "../orders";
import type { AIChange, BoardState, MapReport, UserBrief, VariantDetail } from "../types";

function TopBar({ title, back = "#/variants" }: { title: string; back?: string }) {
  return (
    <header className="topbar">
      <a href={back} className="back">
        ‹ Back
      </a>
      <div className="title">
        <strong>{title}</strong>
      </div>
    </header>
  );
}

function errorReport(e: unknown): MapReport {
  if (e instanceof ApiError && e.detail && typeof e.detail === "object" && "errors" in (e.detail as object)) return e.detail as MapReport;
  return { errors: [(e as Error).message], warnings: [] };
}

export function ReportView({ report, compact }: { report: MapReport; compact?: boolean }) {
  const s = report.stats ?? {};
  return (
    <div className="report">
      {report.errors.length > 0 && (
        <div className="rbox err">
          <strong>{report.errors.length === 1 ? "1 problem to fix" : `${report.errors.length} problems to fix`}</strong>
          <ul>
            {report.errors.map((e, i) => (
              <li key={i}>{e}</li>
            ))}
          </ul>
        </div>
      )}
      {report.warnings.length > 0 && (
        <div className="rbox warn">
          <strong>Worth a look</strong>
          <ul>
            {report.warnings.map((e, i) => (
              <li key={i}>{e}</li>
            ))}
          </ul>
        </div>
      )}
      {!compact && Object.keys(s).length > 0 && (
        <div className="stats">
          {(
            [
              ["Powers", s.powers],
              ["Provinces", s.provinces],
              ["Sea", s.sea],
              ["Supply centers", s.supply_centers],
              ["Neutral centers", s.neutral_centers],
              ["To win", s.victory],
              ["Adjacencies", report.adjacency?.length ?? s.adjacencies],
            ] as [string, unknown][]
          ).map(([k, v]) => (
            <div key={k}>
              <b>{String(v ?? "—")}</b>
              <span>{k}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function AdjLegend() {
  return (
    <div className="adj-legend small muted">
      <span>
        <i className="l both" /> armies &amp; fleets
      </span>
      <span>
        <i className="l army" /> armies only
      </span>
      <span>
        <i className="l fleet" /> fleets only
      </span>
    </div>
  );
}

// ------------------------------------------------------------------ upload

export function MapUpload({ replace }: { replace?: string }) {
  const [specFile, setSpecFile] = useState<File | null>(null);
  const [specText, setSpecText] = useState("");
  const [image, setImage] = useState<File | null>(null);
  const [mask, setMask] = useState<File | null>(null);
  const [busy, setBusy] = useState<"check" | "submit" | null>(null);
  const [report, setReport] = useState<MapReport | null>(null);
  const [preview, setPreview] = useState<MapModel | null>(null);
  const [showAdj, setShowAdj] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const isSvg = !!image && (image.type === "image/svg+xml" || image.name.toLowerCase().endsWith(".svg"));

  useEffect(() => {
    if (!replace) return;
    fetch(`/api/variants/${replace}/files/spec.yaml`, { credentials: "same-origin" })
      .then((r) => (r.ok ? r.text() : ""))
      .then((t) => t && setSpecText(t));
  }, [replace]);

  const imageUrl = useMemo(() => (image ? URL.createObjectURL(image) : null), [image]);
  useEffect(() => () => void (imageUrl && URL.revokeObjectURL(imageUrl)), [imageUrl]);

  const send = async (dry: boolean) => {
    const fd = new FormData();
    if (specFile) fd.append("spec_file", specFile);
    else fd.append("spec_text", specText);
    if (image) fd.append("image", image);
    if (mask && !isSvg) fd.append("mask", mask);
    if (dry) fd.append("dry_run", "true");
    if (replace) fd.append("replace", replace);
    const res = await fetch("/api/variants", { method: "POST", body: fd, credentials: "same-origin" });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new ApiError(res.status, typeof data.detail === "string" ? data.detail : "The map has problems", data.detail);
    return data;
  };

  const check = async () => {
    setBusy("check");
    setPreview(null);
    try {
      const r = await send(true);
      setReport(r.report);
      const geo: MapData = r.geometry;
      if (geo.style === "image" && imageUrl) geo.image = imageUrl;
      setPreview(new MapModel(geo));
    } catch (e) {
      setReport(errorReport(e));
    } finally {
      setBusy(null);
    }
  };

  const submit = async () => {
    setBusy("submit");
    try {
      const v = await send(false);
      location.hash = `#/maps/${v.slug}`;
    } catch (e) {
      setReport(errorReport(e));
      setBusy(null);
    }
  };

  const hasSpec = !!specFile || specText.trim().length > 0;
  const ready = hasSpec && (isSvg || !!mask || (!image && !!mask));

  return (
    <div className="page">
      <TopBar title={replace ? "Update map" : "Upload a map"} back={replace ? `#/maps/${replace}` : "#/variants"} />
      <main className="mapedit">
        <section className="card">
          <h2>{replace ? "Upload a new version" : "Upload a map"}</h2>
          <p className="muted">
            A map is a <b>spec file</b> (YAML or JSON: powers, provinces, supply centers) plus either an <b>SVG</b> whose shapes have province
            codes as their ids, or a <b>PNG/JPEG picture plus a province mask</b> PNG. Adjacencies are worked out automatically — you only
            list the exceptions. <a href="#/maps/guide">Full guide →</a>
          </p>
          <div className="examples small">
            Start from the example:
            <a href="/api/examples/spec.yaml">spec.yaml</a>
            <a href="/api/examples/map.svg">map.svg</a>
            <a href="/api/examples/map.png">map.png</a>
            <a href="/api/examples/mask.png">mask.png</a>
          </div>

          <label>
            Spec (YAML or JSON)
            <input type="file" accept=".yaml,.yml,.json,text/yaml,application/json" onChange={(e) => setSpecFile(e.target.files?.[0] ?? null)} />
          </label>
          {!specFile && (
            <label>
              …or paste it
              <textarea className="mono" rows={replace ? 14 : 6} value={specText} onChange={(e) => setSpecText(e.target.value)} placeholder="name: My Map&#10;powers: …&#10;provinces: …" />
            </label>
          )}
          <label>
            Map image <small className="muted">SVG, PNG or JPEG{replace ? " — leave empty to keep the current one" : ""}</small>
            <input type="file" accept=".svg,.png,.jpg,.jpeg,image/svg+xml,image/png,image/jpeg" onChange={(e) => setImage(e.target.files?.[0] ?? null)} />
          </label>
          {!isSvg && (
            <label>
              Province mask <small className="muted">PNG — each province one flat color from the spec</small>
              <input type="file" accept=".png,image/png" onChange={(e) => setMask(e.target.files?.[0] ?? null)} />
            </label>
          )}
          <div className="row gap">
            <button className="btn" disabled={!hasSpec || !!busy} onClick={check}>
              {busy === "check" ? "Checking…" : "Check map"}
            </button>
            <button className="btn primary" disabled={!(ready || (replace && hasSpec)) || !!busy || (report?.errors.length ?? 0) > 0 || !preview} onClick={submit}>
              {busy === "submit" ? "Submitting…" : replace ? "Save new version" : "Submit for review"}
            </button>
          </div>
          <p className="muted small">Check your map first — submitting is enabled once it passes.</p>
          {report && <ReportView report={report} />}
        </section>

        <section className="card preview-card">
          <div className="section-head small-head">
            <h3>Preview</h3>
            {preview && (
              <label className="inline">
                <input type="checkbox" checked={showAdj} onChange={(e) => setShowAdj(e.target.checked)} /> Show adjacencies
              </label>
            )}
          </div>
          {preview ? (
            <>
              <MapView map={preview} adjacency={showAdj ? report?.adjacency : undefined} showLabels />
              {showAdj && <AdjLegend />}
              <p className="muted small">Hover a line to see which provinces it joins. Dots are where units will stand.</p>
            </>
          ) : (
            <div className="empty">Your map will appear here after a check.</div>
          )}
        </section>
      </main>
      <Toast text={error} onClose={() => setError(null)} />
    </div>
  );
}

// ------------------------------------------------------------ detail/review

function changeText(c: AIChange): ReactNode {
  switch (c.op) {
    case "add_adjacency":
      return (
        <>
          Connect <b>{c.a}</b> ↔ <b>{c.b}</b> ({c.type === "both" ? "armies & fleets" : `${c.type}s only`})
        </>
      );
    case "remove_adjacency":
      return (
        <>
          Disconnect <b>{c.a}</b> ↔ <b>{c.b}</b>
        </>
      );
    case "set_impassable":
      return (
        <>
          Make <b>{c.code}</b> {c.value ? "impassable" : "passable"}
        </>
      );
    case "set_supply_center":
      return (
        <>
          {c.value ? "Make" : "Remove"} supply center <b>{c.code}</b>
        </>
      );
    case "set_build_anywhere":
      return <>{c.value ? "Allow builds in any owned center" : "Builds in home centers only"}</>;
    case "set_victory":
      return <>Victory at {String(c.value)} supply centers</>;
    default:
      return c.op;
  }
}

export function MapDetail({ slug, me }: { slug: string; me: UserBrief }) {
  const [v, setV] = useState<VariantDetail | null>(null);
  const [notFound, setNotFound] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [picked, setPicked] = useState<Set<number>>(new Set());
  const [note, setNote] = useState("");
  const [showAdj, setShowAdj] = useState(true);
  const [start, setStart] = useState<BoardState | null>(null);
  const [manual, setManual] = useState({ a: "", b: "", type: "both" });

  const load = useCallback(() => {
    api
      .get<VariantDetail>(`/variants/${slug}`)
      .then((d) => {
        setV(d);
        setPicked(new Set((d.ai?.changes ?? []).filter((c) => !c.applied).map((c) => c.id)));
      })
      .catch((e) => (e.status === 404 ? setNotFound(true) : setError(e.message)));
  }, [slug]);
  useEffect(load, [load]);
  useLive((e) => e.type === "variants" && e.slug === slug && load(), [slug, load]);

  const map = useMap(v ? `/variants/${slug}/map?v=${v.version ?? 0}` : null);
  useEffect(() => {
    if (v) api.get<BoardState>(`/variants/${slug}/start?v=${v.version ?? 0}`).then(setStart).catch(() => {});
  }, [slug, v?.version]); // eslint-disable-line react-hooks/exhaustive-deps

  const act = async (label: string, fn: () => Promise<VariantDetail | unknown>) => {
    setBusy(label);
    try {
      const r = await fn();
      if (r && typeof r === "object" && "slug" in (r as object)) {
        setV(r as VariantDetail);
        setPicked(new Set(((r as VariantDetail).ai?.changes ?? []).filter((c) => !c.applied).map((c) => c.id)));
      }
    } catch (e) {
      const rep = errorReport(e);
      setError(rep.errors.join(" "));
    } finally {
      setBusy(null);
    }
  };

  if (notFound)
    return (
      <div className="center-page">
        <div className="card narrow">
          <h2>Map not found</h2>
          <a className="btn" href="#/variants">
            Back
          </a>
        </div>
      </div>
    );
  if (!v) return <div className="center-page muted">Loading map…</div>;

  const applySelected = () =>
    act("apply", () =>
      api.post(`/variants/${slug}/apply`, { changes: (v.ai?.changes ?? []).filter((c) => picked.has(c.id)) }),
    );
  const applyManual = () => {
    const a = manual.a.trim().toUpperCase();
    const b = manual.b.trim().toUpperCase();
    if (!a || !b) return;
    const change = manual.type === "remove" ? { op: "remove_adjacency", a, b } : { op: "add_adjacency", a, b, type: manual.type };
    act("manual", () => api.post(`/variants/${slug}/apply`, { changes: [change] })).then(() => setManual({ a: "", b: "", type: "both" }));
  };
  const statusText = { approved: "Live", pending: "Awaiting review", rejected: "Changes requested", builtin: "Built in" }[v.status];

  return (
    <div className="page">
      <TopBar title={v.name} back={me.is_admin && v.status === "pending" ? "#/review" : "#/variants"} />
      <main className="mapedit">
        <section className="card preview-card">
          <div className="section-head small-head">
            <div>
              <h2 className="inline-h">{v.name}</h2> <span className={`tag status-${v.status}`}>{statusText}</span>
              <div className="muted small">
                {v.author && <>by {v.author.display_name} · </>}
                {v.players} powers · {v.supply_centers} centers · {v.victory} to win
                {v.games ? ` · ${v.games} game${v.games > 1 ? "s" : ""}` : ""}
              </div>
            </div>
            {v.report?.adjacency && (
              <label className="inline">
                <input type="checkbox" checked={showAdj} onChange={(e) => setShowAdj(e.target.checked)} /> Adjacencies
              </label>
            )}
          </div>
          {map ? <MapView map={map} board={start} adjacency={showAdj ? v.report?.adjacency : undefined} showLabels={showAdj || undefined} /> : <div className="empty">Loading…</div>}
          {showAdj && v.report?.adjacency && <AdjLegend />}
          {v.description && <p>{v.description}</p>}
          <div className="powers-row">
            {v.powers.map((p) => (
              <span key={p.name} className="chip">
                <span className="dot" style={{ background: p.color || powerColor(p.name) }} />
                {titleCase(p.name)}
              </span>
            ))}
          </div>
        </section>

        <section className="side-stack">
          {v.can_review && (
            <div className="card review-card">
              <h3>Review</h3>
              <textarea rows={2} placeholder="Note to the author (optional)" value={note} onChange={(e) => setNote(e.target.value)} />
              <div className="row gap">
                {v.status !== "approved" && (
                  <button className="btn primary" disabled={!!busy || (v.report?.errors.length ?? 0) > 0} onClick={() => act("review", () => api.post(`/variants/${slug}/review`, { action: "approve", note }))}>
                    Approve
                  </button>
                )}
                {v.status !== "rejected" && (
                  <button className="btn" disabled={!!busy} onClick={() => act("review", () => api.post(`/variants/${slug}/review`, { action: "reject", note }))}>
                    Request changes
                  </button>
                )}
                {v.status === "approved" && (
                  <button className="btn ghost" disabled={!!busy} onClick={() => act("review", () => api.post(`/variants/${slug}/review`, { action: "unpublish", note }))}>
                    Unpublish
                  </button>
                )}
              </div>
              <p className="muted small">Before approving, check the adjacency lines on the map — especially straits, canals and split coasts.</p>
            </div>
          )}
          {v.review_note && (
            <div className="card">
              <h3>Reviewer's note</h3>
              <p>{v.review_note}</p>
            </div>
          )}

          {v.report && (
            <div className="card">
              <h3>Checks</h3>
              <ReportView report={v.report} />
            </div>
          )}

          <div className="card">
            <h3>Special rules</h3>
            {v.rules_text ? <p className="rules">{v.rules_text}</p> : <p className="muted small">None — the map plays by the standard rules.</p>}
            {v.can_manage && v.rules_text && (
              <div className="ai">
                {!v.ai && (
                  <p className="muted small">
                    {v.ai_enabled ? "The AI can read these rules and propose matching map changes for you to approve." : "Set ANTHROPIC_API_KEY on the server to have an AI turn these rules into map changes."}
                  </p>
                )}
                {v.ai?.error && <div className="rbox err small">{v.ai.error}</div>}
                {v.ai && !v.ai.error && (
                  <>
                    {v.ai.summary && <p className="small">{v.ai.summary}</p>}
                    {(v.ai.changes ?? []).length > 0 && (
                      <ul className="changes">
                        {v.ai.changes!.map((c) => (
                          <li key={c.id} className={c.applied ? "applied" : ""}>
                            <label className="inline">
                              <input
                                type="checkbox"
                                disabled={c.applied}
                                checked={c.applied || picked.has(c.id)}
                                onChange={(e) => {
                                  const n = new Set(picked);
                                  if (e.target.checked) n.add(c.id);
                                  else n.delete(c.id);
                                  setPicked(n);
                                }}
                              />
                              <span>
                                <span className="ctext">
                                  {changeText(c)}
                                  {c.applied && <span className="tag">applied</span>}
                                </span>
                                <small className="muted">
                                  “{c.rule}” — {c.explanation}
                                </small>
                              </span>
                            </label>
                          </li>
                        ))}
                      </ul>
                    )}
                    {(v.ai.unenforceable ?? []).length > 0 && (
                      <div className="rbox warn small">
                        <strong>Can't be enforced by the engine</strong> — players would follow these on the honor system:
                        <ul>
                          {v.ai.unenforceable!.map((u, i) => (
                            <li key={i}>
                              “{u.rule}” — {u.explanation}
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}
                    {picked.size > 0 && (
                      <button className="btn small primary" disabled={!!busy} onClick={applySelected}>
                        {busy === "apply" ? "Applying…" : `Apply ${picked.size} change${picked.size > 1 ? "s" : ""}`}
                      </button>
                    )}
                  </>
                )}
                {v.ai_enabled && (
                  <button className="btn small" disabled={!!busy} onClick={() => act("ai", () => api.post(`/variants/${slug}/ai`))}>
                    {busy === "ai" ? "Reading the rules…" : v.ai ? "Ask again" : "Interpret rules with AI"}
                  </button>
                )}
              </div>
            )}
          </div>

          {v.can_manage && (
            <div className="card">
              <h3>Fix an adjacency</h3>
              <div className="row gap manual">
                <input placeholder="ABC" value={manual.a} maxLength={6} onChange={(e) => setManual({ ...manual, a: e.target.value })} />
                <input placeholder="XYZ" value={manual.b} maxLength={6} onChange={(e) => setManual({ ...manual, b: e.target.value })} />
                <select value={manual.type} onChange={(e) => setManual({ ...manual, type: e.target.value })}>
                  <option value="both">connect: both</option>
                  <option value="army">connect: armies</option>
                  <option value="fleet">connect: fleets</option>
                  <option value="remove">disconnect</option>
                </select>
                <button className="btn small" disabled={!!busy} onClick={applyManual}>
                  Apply
                </button>
              </div>
              <p className="muted small">Use coast codes like ABC/NC for fleets on split coasts. Every change re-runs all checks.</p>
            </div>
          )}

          {(v.can_manage || v.status === "approved") && !v.builtin && (
            <div className="card">
              <h3>Files</h3>
              <div className="examples small">
                <a href={`/api/variants/${slug}/files/spec.yaml`}>spec.yaml</a>
                <a href={`/api/variants/${slug}/files/mask.png`}>mask.png</a>
                {v.has_image && (
                  <a href={`/api/variants/${slug}/image`} target="_blank" rel="noreferrer">
                    artwork
                  </a>
                )}
                <a href={`/api/variants/${slug}/files/engine.map`} target="_blank" rel="noreferrer">
                  engine .map
                </a>
              </div>
              {v.can_manage && (
                <div className="row gap" style={{ marginTop: 10 }}>
                  {(v.status !== "approved" || me.is_admin) && (
                    <a className="btn small" href={`#/maps/${slug}/edit`}>
                      Upload new version
                    </a>
                  )}
                  {!v.games && (
                    <button
                      className="btn small ghost"
                      onClick={() =>
                        confirm("Delete this map?") &&
                        act("delete", async () => {
                          await api.del(`/variants/${slug}`);
                          location.hash = "#/variants";
                        })
                      }
                    >
                      Delete
                    </button>
                  )}
                </div>
              )}
            </div>
          )}
        </section>
      </main>
      <Toast text={error} onClose={() => setError(null)} />
    </div>
  );
}

// ------------------------------------------------------------------- guide

export function MapGuide() {
  return (
    <div className="page">
      <TopBar title="How to make a map" />
      <main className="guide card">
        <h2>Making a map for Entente</h2>
        <p>
          A map has two parts: a <b>picture</b> that says where each province is, and a <b>spec</b> that says what each province is. The site
          works out which provinces border each other, where units stand and how the engine should treat coasts, then shows you a preview.
          The admin approves maps before they appear in everyone's Variants pane.
        </p>
        <p className="examples">
          Example files: <a href="/api/examples/spec.yaml">spec.yaml</a> <a href="/api/examples/map.svg">map.svg</a> <a href="/api/examples/map.png">map.png</a>{" "}
          <a href="/api/examples/mask.png">mask.png</a>
        </p>

        <h3>1. The picture — pick one route</h3>
        <ul>
          <li>
            <b>SVG (easiest if you draw in Inkscape, Illustrator, Figma…)</b>: give every province shape an <code>id</code> equal to its 3-letter code
            (<code>id="PAR"</code>). Shapes can be paths, polygons or rects; groups and transforms are fine. Other shapes are kept as decoration.
          </li>
          <li>
            <b>PNG or JPEG + a province mask PNG</b>: the picture is shown as-is. The mask is a same-sized PNG where every province is painted one
            flat color — the color you list for it in the spec. Thin black borders between provinces are fine. Save the mask as PNG (JPEG blurs colors).
          </li>
          <li>
            <b>Mask only</b>: upload just the mask and the site draws a plain map from it.
          </li>
        </ul>

        <h3>2. The spec (YAML or JSON)</h3>
        <table className="spec">
          <tbody>
            <tr>
              <td>
                <code>name</code>, <code>description</code>
              </td>
              <td>Shown in the Variants pane.</td>
            </tr>
            <tr>
              <td>
                <code>provinces</code>
              </td>
              <td>
                One entry per province: <code>code</code> (exactly 3 letters), <code>name</code>, <code>type</code> (<code>land</code> or{" "}
                <code>sea</code> — coasts are detected automatically), <code>sc: true</code> for supply centers, <code>impassable: true</code> for
                provinces nobody may enter, and <code>color</code> (mask color, PNG route only).
              </td>
            </tr>
            <tr>
              <td>
                <code>coasts</code>
              </td>
              <td>
                Only for provinces with two separate coastlines (like Spain or St Petersburg): list each coast with a 2-letter name and the seas it
                touches, e.g. <code>{"{name: NC, seas: [MAO, GAS]}"}</code>.
              </td>
            </tr>
            <tr>
              <td>
                <code>powers</code>
              </td>
              <td>
                For each player: <code>name</code> (one word, not 3 letters long, e.g. <code>FRANCE</code>), <code>adjective</code>, <code>color</code>,{" "}
                <code>homes</code> (their home supply centers) and starting <code>units</code> like <code>"A PAR"</code>, <code>"F BRE"</code>,{" "}
                <code>"F STP/SC"</code>.
              </td>
            </tr>
            <tr>
              <td>Neutral centers</td>
              <td>Automatic: every supply center that isn't anyone's home.</td>
            </tr>
            <tr>
              <td>
                <code>victory</code>
              </td>
              <td>Supply centers needed to win. Default: more than half.</td>
            </tr>
            <tr>
              <td>
                <code>build_anywhere</code>
              </td>
              <td>
                <code>true</code> lets powers build in any center they own (not just home centers).
              </td>
            </tr>
            <tr>
              <td>
                <code>start_year</code>
              </td>
              <td>Default 1901.</td>
            </tr>
            <tr>
              <td>
                <code>adjacency</code>
              </td>
              <td>
                Fixes for the automatic borders: <code>add: [["AAA", "CCC", "fleet"]]</code> (types: <code>both</code>, <code>army</code>,{" "}
                <code>fleet</code>) and <code>remove: [["AAA", "BBB"]]</code>. Canals, straits and bridges go here.
              </td>
            </tr>
            <tr>
              <td>
                <code>rules</code>
              </td>
              <td>
                Plain-English special rules. The reviewer can have an AI translate them into adjacency changes before approval. Anything the engine
                can't express is shown to players as an honor-system house rule.
              </td>
            </tr>
          </tbody>
        </table>

        <h3>3. How borders are detected</h3>
        <ul>
          <li>Two provinces border each other when their areas touch (borders a few pixels wide are fine; a single corner doesn't count).</li>
          <li>Sea–sea and sea–coast borders carry fleets. Land borders carry armies.</li>
          <li>Two coastal provinces also carry fleets when their shared border reaches the sea.</li>
          <li>Check the preview's adjacency lines and fix anything surprising with the <code>adjacency</code> lists.</li>
        </ul>

        <h3>4. Submit</h3>
        <p>
          Upload, press <b>Check map</b>, fix any problems, then <b>Submit for review</b>. You can playtest your own map before it's approved — it
          appears in the New game menu for you.
        </p>
      </main>
    </div>
  );
}
