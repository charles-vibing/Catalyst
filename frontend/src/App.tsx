import { useEffect, useState } from "react";
import {
  Episode,
  EpisodeDetailResponse,
  EpisodeStatus,
  QueueItem,
  RosterResponse,
  fetchEpisode,
  fetchQueue,
  fetchRoster,
} from "./api";
import EpisodeDetail from "./EpisodeDetail";
import TriageQueue from "./TriageQueue";

type StatusFilter = "all" | "active" | "completed";
type SortKey = "status" | "days" | "patient" | "disposition";
type SortDir = "asc" | "desc";

const STATUS_FILTERS: { id: StatusFilter; label: string }[] = [
  { id: "all", label: "All" },
  { id: "active", label: "Active" },
  { id: "completed", label: "Completed" },
];

const COLUMNS: { key: SortKey; label: string }[] = [
  { key: "patient", label: "Patient" },
  { key: "disposition", label: "Disposition" },
  { key: "days", label: "Days left" },
  { key: "status", label: "Status" },
];

const STATUS_RANK: Record<string, number> = { active: 0, completed: 1 };

function dispositionClass(disposition: string | null): string {
  const d = (disposition ?? "").toLowerCase();
  if (d.includes("skilled nursing")) return "chip chip-snf";
  if (d.includes("rehab") || d.includes("irf")) return "chip chip-irf";
  if (d.includes("home health")) return "chip chip-hha";
  if (d.includes("home")) return "chip chip-home";
  return "chip chip-other";
}

function fmtDate(iso: string | null): string {
  if (!iso) return "—";
  const [y, m, d] = iso.split("-");
  return `${m}/${d}/${y}`;
}

function cmpNullable(
  a: string | number | null | undefined,
  b: string | number | null | undefined,
): number {
  if (a == null && b == null) return 0;
  if (a == null) return 1;
  if (b == null) return -1;
  if (a < b) return -1;
  if (a > b) return 1;
  return 0;
}

function sortEpisodes(list: Episode[], key: SortKey, dir: SortDir): Episode[] {
  const mul = dir === "asc" ? 1 : -1;
  return [...list].sort((a, b) => {
    let c = 0;
    switch (key) {
      case "status":
        c = (STATUS_RANK[a.status] ?? 9) - (STATUS_RANK[b.status] ?? 9);
        if (c === 0) c = cmpNullable(a.days_remaining, b.days_remaining);
        break;
      case "days":
        c = cmpNullable(a.days_remaining, b.days_remaining);
        break;
      case "patient":
        c = cmpNullable(a.patient_name.toLowerCase(), b.patient_name.toLowerCase());
        break;
      case "disposition":
        c = cmpNullable(
          (a.disposition ?? "").toLowerCase(),
          (b.disposition ?? "").toLowerCase(),
        );
        break;
    }
    if (c === 0) {
      c = cmpNullable(a.patient_name.toLowerCase(), b.patient_name.toLowerCase());
    }
    return c * mul;
  });
}

function EpisodeRow({
  e,
  selected,
  onSelect,
}: {
  e: Episode;
  selected: boolean;
  onSelect: (fin: string) => void;
}) {
  const demo = [e.age != null ? `${e.age}${e.sex ?? ""}` : null, e.procedure_summary]
    .filter(Boolean)
    .join(" · ");

  return (
    <tr
      className={selected ? "selected" : undefined}
      onClick={() => onSelect(e.fin)}
      tabIndex={0}
      onKeyDown={(ev) => {
        if (ev.key === "Enter" || ev.key === " ") {
          ev.preventDefault();
          onSelect(e.fin);
        }
      }}
    >
      <td>
        <span className="patient-name">{e.patient_name}</span>
        {demo && <span className="patient-sub">{demo}</span>}
        <span className="patient-sub">
          {fmtDate(e.admit_date)} → {fmtDate(e.discharge_date)}
        </span>
        <span className="patient-sub">MRN {e.mrn}</span>
      </td>
      <td>
        <span className={dispositionClass(e.disposition)}>
          {e.disposition ?? "Unknown"}
        </span>
      </td>
      <td className="days">{e.days_remaining ?? "—"}</td>
      <td>
        <span className={`status status-${e.status}`}>{e.status}</span>
      </td>
    </tr>
  );
}

export default function App() {
  const [data, setData] = useState<RosterResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [sortKey, setSortKey] = useState<SortKey>("status");
  const [sortDir, setSortDir] = useState<SortDir>("asc");
  const [selectedFin, setSelectedFin] = useState<string | null>(null);
  const [detail, setDetail] = useState<EpisodeDetailResponse | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [queueItems, setQueueItems] = useState<QueueItem[]>([]);
  const [queueLoading, setQueueLoading] = useState(true);
  const [queueError, setQueueError] = useState<string | null>(null);
  const [selectedQueueId, setSelectedQueueId] = useState<number | null>(null);

  useEffect(() => {
    fetchRoster()
      .then((roster) => {
        setData(roster);
        setSelectedFin((prev) => {
          if (prev || roster.episodes.length === 0) return prev;
          const firstActive =
            roster.episodes.find((e) => e.status === "active") ?? roster.episodes[0];
          return firstActive.fin;
        });
      })
      .catch((err) => setError(String(err)));
  }, []);

  useEffect(() => {
    setQueueLoading(true);
    fetchQueue("open")
      .then((q) => setQueueItems(q.items))
      .catch((err) => setQueueError(String(err)))
      .finally(() => setQueueLoading(false));
  }, []);

  useEffect(() => {
    if (!selectedFin) {
      setDetail(null);
      setDetailError(null);
      return;
    }
    let cancelled = false;
    setDetailLoading(true);
    setDetailError(null);
    fetchEpisode(selectedFin)
      .then((d) => {
        if (!cancelled) setDetail(d);
      })
      .catch((err) => {
        if (!cancelled) {
          setDetail(null);
          setDetailError(String(err));
        }
      })
      .finally(() => {
        if (!cancelled) setDetailLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [selectedFin]);

  function onQueueSelect(item: QueueItem) {
    setSelectedQueueId(item.id);
    if (item.fin) setSelectedFin(item.fin);
  }

  function onQueueResolved(id: number) {
    setQueueItems((prev) => prev.filter((i) => i.id !== id));
    setSelectedQueueId((prev) => (prev === id ? null : prev));
  }

  const meta = data?.meta;
  const counts = meta?.status_counts ?? {};

  const episodes = data?.episodes ?? [];
  const filtered =
    statusFilter === "all"
      ? episodes
      : episodes.filter((e) => e.status === (statusFilter as EpisodeStatus));
  const rows = sortEpisodes(filtered, sortKey, sortDir);

  function onSort(key: SortKey) {
    if (key === sortKey) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir("asc");
    }
  }

  return (
    <div className="wrap">
      <header>
        <div className="brand">
          <h1>SHFFT Episode Command</h1>
          <p>{meta?.org_name ?? "…"}</p>
        </div>
        <div className="header-meta">
          {meta ? (
            <>
              <div>
                As-of <strong>{fmtDate(meta.as_of)}</strong>{" "}
                <span className={`mode mode-${meta.as_of_mode}`}>
                  {meta.as_of_mode === "frozen" ? "frozen demo" : "live today()"}
                </span>
              </div>
              <div className="counts">
                {meta.total} episodes · {counts.active ?? 0} active ·{" "}
                {counts.completed ?? 0} completed
              </div>
            </>
          ) : (
            <div>Loading…</div>
          )}
          <span className="synthetic-tag">Synthetic data</span>
        </div>
      </header>

      {error && <div className="error">Failed to load roster: {error}</div>}

      <div className="grid-main">
        <section className="panel">
          <div className="panel-h">
            <h2>Episode roster</h2>
            <span className="dtag">D1 · D9 (read-only, M1)</span>
          </div>
          <div className="filters" role="group" aria-label="Filter by status">
            <span className="toolbar-label">Filter</span>
            {STATUS_FILTERS.map((f) => (
              <button
                key={f.id}
                type="button"
                className={statusFilter === f.id ? "active" : undefined}
                onClick={() => setStatusFilter(f.id)}
              >
                {f.label}
                {f.id !== "all" && (
                  <span className="filter-count">{counts[f.id] ?? 0}</span>
                )}
              </button>
            ))}
          </div>
          <div className="roster-scroll">
            <table className="roster">
              <thead>
                <tr>
                  {COLUMNS.map((col) => {
                    const active = sortKey === col.key;
                    return (
                      <th
                        key={col.key}
                        aria-sort={
                          active
                            ? sortDir === "asc"
                              ? "ascending"
                              : "descending"
                            : "none"
                        }
                      >
                        <button
                          type="button"
                          className={`th-sort${active ? " sorted" : ""}`}
                          onClick={() => onSort(col.key)}
                        >
                          {col.label}
                          <span className="sort-ind" aria-hidden="true">
                            {active ? (sortDir === "asc" ? "↑" : "↓") : "↕"}
                          </span>
                        </button>
                      </th>
                    );
                  })}
                </tr>
              </thead>
              <tbody>
                {rows.map((e) => (
                  <EpisodeRow
                    key={e.fin}
                    e={e}
                    selected={e.fin === selectedFin}
                    onSelect={(fin) => {
                      setSelectedFin(fin);
                      setSelectedQueueId(null);
                    }}
                  />
                ))}
                {data && rows.length === 0 && (
                  <tr>
                    <td colSpan={4} className="empty">
                      No episodes match this filter.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </section>

        <TriageQueue
          items={queueItems}
          loading={queueLoading}
          error={queueError}
          selectedId={selectedQueueId}
          onSelect={onQueueSelect}
          onResolved={onQueueResolved}
        />
      </div>

      <section className="panel detail" aria-labelledby="detail-title">
        <div className="panel-h">
          <h2 id="detail-title">Patient episode view</h2>
          <span className="dtag">D4 · D9 (M2)</span>
        </div>
        <EpisodeDetail detail={detail} loading={detailLoading} error={detailError} />
      </section>
    </div>
  );
}
