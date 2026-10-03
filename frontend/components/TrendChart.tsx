"use client";

import { useMemo, useState } from "react";
import { useApp } from "@/lib/app-context";
import { fmtDate } from "@/lib/format";
import type { FollowUp, TrendPoint } from "@/types/brief";

/*
 * "Since last visit" as small multiples on one shared date axis (never a dual axis):
 *   Focus 0–10 · Sleep in hours (self-reported vs. wearable) · Resting heart rate (wearable).
 * Patient-reported values: solid amber line with ring markers. Device values: dashed muted line.
 * The clinic's dose change is a cobalt rule across all panels. Hover = crosshair + tooltip; a table view
 * carries the same data without colour.
 */

type Panel = {
  key: string;
  title: string;
  unit: string;
  min: number;
  max: number;
  ticks: number[];
  self?: (p: TrendPoint) => number | null;
  device?: (p: TrendPoint) => number | null;
};

const L = 34;
const R = 14;
const PH = 84; // panel plot height
const GAP = 34; // title + spacing above each panel

export function TrendChart({ data, compact = false }: { data: FollowUp; compact?: boolean }) {
  const { t, lang } = useApp();
  const [hover, setHover] = useState<number | null>(null);

  const panels: Panel[] = useMemo(() => {
    const all: Panel[] = [
      { key: "focus", title: t("trend.focus"), unit: "/10", min: 0, max: 10, ticks: [0, 5, 10], self: (p) => p.focus },
      { key: "sleep", title: t("trend.sleep"), unit: " h", min: 4, max: 9, ticks: [4, 6, 8],
        self: (p) => p.sleepSelf, device: (p) => p.sleepDevice },
      { key: "hr", title: t("trend.hr"), unit: " bpm", min: 55, max: 80, ticks: [60, 70, 80], device: (p) => p.restingHr },
    ];
    return compact ? all.slice(0, 2) : all.filter((p) => data.series.some((s) => (p.self?.(s) ?? p.device?.(s)) != null));
  }, [compact, data.series, t]);

  const W = compact ? 380 : 640; // narrower canvas on the phone keeps text legible
  const n = data.series.length;
  const H = panels.length * (PH + GAP) + 26;
  const x = (i: number) => L + (n <= 1 ? 0 : (i * (W - L - R)) / (n - 1));
  const top = (pi: number) => pi * (PH + GAP) + GAP - 8;
  const y = (pi: number, v: number) => {
    const p = panels[pi];
    const c = Math.max(p.min, Math.min(p.max, v));
    return top(pi) + PH - ((c - p.min) / (p.max - p.min)) * PH;
  };
  const path = (pi: number, get: (p: TrendPoint) => number | null) => {
    let d = "";
    let pen = false;
    data.series.forEach((s, i) => {
      const v = get(s);
      if (v == null) { pen = false; return; }
      d += `${pen ? "L" : "M"}${x(i).toFixed(1)},${y(pi, v).toFixed(1)}`;
      pen = true;
    });
    return d;
  };
  const splitIdx = data.split ? data.series.findIndex((s) => s.date >= data.split!) : -1;
  const xTicks = n ? [0, Math.round((n - 1) / 3), Math.round((2 * (n - 1)) / 3), n - 1].filter((v, i, a) => a.indexOf(v) === i) : [];
  const short = (d: string) => fmtDate(d, lang).replace(/\s\d{4}$/, "");
  const medLabel = (m: TrendPoint["med"]) => (m ? t(`trend.med.${m}` as "trend.med.on_time") : "–");

  function onMove(e: React.PointerEvent<SVGRectElement>) {
    const box = (e.currentTarget.ownerSVGElement as SVGSVGElement).getBoundingClientRect();
    const px = ((e.clientX - box.left) / box.width) * W;
    const i = Math.round(((px - L) / (W - L - R)) * (n - 1));
    setHover(Math.max(0, Math.min(n - 1, i)));
  }
  const hp = hover != null ? data.series[hover] : null;
  const tipLeft = hover != null ? `${Math.min(70, Math.max(0, (x(hover) / W) * 100 - 10))}%` : "0";

  if (!n) return <p className="small">{t("trend.empty")}</p>;
  return (
    <div className="trend" style={{ position: "relative" }}>
      <div className="trend-head" aria-hidden="true">
        <span className="key"><i /> {t("trend.self")}</span>
        <span className="key"><i className="dash" /> {t("trend.device")}</span>
        {splitIdx >= 0 && <span className="key"><i className="event" /> {t("trend.event")}</span>}
        <span className="key"><i className="sq" /> {t("trend.missedKey")}</span>
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={t("trend.aria", { from: fmtDate(data.series[0].date, lang), to: fmtDate(data.series[n - 1].date, lang) })}>
        {panels.map((p, pi) => (
          <g key={p.key}>
            <text className="panel-title" x={L} y={top(pi) - 10}>{p.title}</text>
            {p.ticks.map((tv) => (
              <g key={tv}>
                <line className="grid" x1={L} x2={W - R} y1={y(pi, tv)} y2={y(pi, tv)} />
                <text className="axis" x={L - 6} y={y(pi, tv) + 4} textAnchor="end">{tv}</text>
              </g>
            ))}
            {p.device && <path className="line device" d={path(pi, p.device)} />}
            {p.self && <path className="line" d={path(pi, p.self)} />}
            {p.self && data.series.map((s, i) => {
              const v = p.self!(s);
              return v == null ? null : <circle key={i} className="dot" cx={x(i)} cy={y(pi, v)} r={hover === i ? 4.5 : 3} />;
            })}
            {p.key === "focus" && data.series.map((s, i) => s.med === "missed"
              ? <rect key={`m${i}`} className="missed" x={x(i) - 4} y={top(pi) + PH + 4} width={8} height={8} rx={1} /> : null)}
          </g>
        ))}
        {splitIdx >= 0 && (
          <g>
            <line className="event" x1={x(splitIdx)} x2={x(splitIdx)} y1={GAP - 14} y2={H - 26} />
            <text className="event-label" x={x(splitIdx) + 5} y={GAP - 18}>{data.splitLabel?.replace(/^Methylphenidate ER /, "")}</text>
          </g>
        )}
        {xTicks.map((i) => (
          <text key={i} className="axis" x={x(i)} y={H - 6} textAnchor={i === 0 ? "start" : i === n - 1 ? "end" : "middle"}>{short(data.series[i].date)}</text>
        ))}
        {hover != null && <line className="cross" x1={x(hover)} x2={x(hover)} y1={GAP - 14} y2={H - 26} />}
        <rect x={L - 8} y={0} width={W - L - R + 16} height={H - 20} fill="transparent"
              onPointerMove={onMove} onPointerLeave={() => setHover(null)} />
      </svg>
      {hp && (
        <div className="tip" style={{ left: tipLeft, top: 28 }} role="status">
          <b className="num">{fmtDate(hp.date, lang)}</b>
          {hp.ref ? (
            <>
              <span>{t("trend.focus")}: <b className="num">{hp.focus ?? "–"}/10</b></span>
              <span>{t("trend.sleepSelfShort")}: <b className="num">{hp.sleepSelf ?? "–"} h</b></span>
              <span>{t("trend.medShort")}: {medLabel(hp.med)}</span>
              {hp.sideEffects.length > 0 && <span>{t("trend.noticed")}: {hp.sideEffects.map((s) => t(`trend.side.${s}` as "trend.side.insomnia")).join(", ")}</span>}
              {hp.note && <span style={{ fontStyle: "italic" }}>“{hp.note}”</span>}
            </>
          ) : <span className="small">{t("trend.noCheckin")}</span>}
          {!compact && hp.sleepDevice != null && <span>{t("trend.sleepDeviceShort")}: <b className="num">{hp.sleepDevice} h</b></span>}
          {!compact && hp.restingHr != null && <span>{t("trend.hr")}: <b className="num">{hp.restingHr} bpm</b></span>}
        </div>
      )}
      <details className="trend-table">
        <summary>{t("trend.table")}</summary>
        <div className="table-wrap">
          <table className="log">
            <thead><tr><th>{t("trend.date")}</th><th>{t("trend.focus")}</th><th>{t("trend.sleepSelfShort")}</th>
              {!compact && <th>{t("trend.sleepDeviceShort")}</th>}{!compact && <th>{t("trend.hr")}</th>}<th>{t("trend.medShort")}</th><th>{t("trend.noticed")}</th></tr></thead>
            <tbody>
              {data.series.map((s) => (
                <tr key={s.date}>
                  <td className="num">{fmtDate(s.date, lang)}</td><td className="num">{s.focus ?? "–"}</td><td className="num">{s.sleepSelf ?? "–"}</td>
                  {!compact && <td className="num">{s.sleepDevice ?? "–"}</td>}{!compact && <td className="num">{s.restingHr ?? "–"}</td>}
                  <td>{medLabel(s.med)}</td>
                  <td>{s.sideEffects.map((x) => t(`trend.side.${x}` as "trend.side.insomnia")).join(", ")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </div>
  );
}
