"use client";

import { useRef, useState } from "react";

type DataPoint = { t: string; v: number };

type Props = {
  data: DataPoint[];
  color: string;
  height?: number;
  formatValue?: (v: number) => string;
};

export function MiniAreaChart({ data, color, height = 140, formatValue = (v) => "$" + v }: Props) {
  const [tooltip, setTooltip] = useState<{ x: number; y: number; point: DataPoint } | null>(null);
  const svgRef = useRef<SVGSVGElement>(null);

  const W = 600;
  const H = height;
  const padLeft = 36;
  const padRight = 8;
  const padTop = 8;
  const padBottom = 24;

  const values = data.map((d) => d.v);
  const minV = Math.min(...values);
  const maxV = Math.max(...values);
  const rangeV = maxV - minV || 1;

  const toX = (i: number) => padLeft + ((W - padLeft - padRight) * i) / (data.length - 1);
  const toY = (v: number) => padTop + (H - padTop - padBottom) * (1 - (v - minV) / rangeV);

  const points = data.map((d, i) => [toX(i), toY(d.v)] as [number, number]);
  const linePath = points.map(([x, y], i) => (i === 0 ? "M" : "L") + " " + x.toFixed(1) + " " + y.toFixed(1)).join(" ");
  const areaPath = [linePath, "L " + points[points.length - 1][0].toFixed(1) + " " + (H - padBottom).toFixed(1), "L " + points[0][0].toFixed(1) + " " + (H - padBottom).toFixed(1), "Z"].join(" ");

  const yTicks = [minV, minV + rangeV / 2, maxV];
  const xStep = Math.ceil(data.length / 5);
  const xTickIndices = data.map((_, i) => i).filter((i) => i % xStep === 0 || i === data.length - 1);
  const gradId = "area-grad-" + color.replace(/[^a-z0-9]/gi, "");

  const onMove = (e: React.MouseEvent<SVGSVGElement>) => {
    const rect = svgRef.current?.getBoundingClientRect();
    if (!rect) return;
    const relX = ((e.clientX - rect.left) / rect.width) * W;
    const idx = points.reduce((best, [x], i) => (Math.abs(x - relX) < Math.abs(points[best][0] - relX) ? i : best), 0);
    setTooltip({ x: points[idx][0], y: points[idx][1], point: data[idx] });
  };

  return (
    <div style={{ position: "relative", width: "100%", height }}>
      <svg ref={svgRef} viewBox={"0 0 " + W + " " + H} preserveAspectRatio="none" style={{ width: "100%", height: "100%", display: "block" }} onMouseMove={onMove} onMouseLeave={() => setTooltip(null)}>
        <defs>
          <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity={0.22} />
            <stop offset="100%" stopColor={color} stopOpacity={0.02} />
          </linearGradient>
        </defs>
        {yTicks.map((v, i) => {
          const y = toY(v);
          return (
            <g key={"y" + i}>
              <line x1={padLeft} y1={y} x2={W - padRight} y2={y} stroke="rgb(var(--border))" strokeWidth={0.5} />
              <text x={padLeft - 4} y={y + 4} textAnchor="end" fontSize={9} fill="rgb(var(--muted-foreground))" fontFamily="var(--font-mono)">{formatValue(Math.round(v))}</text>
            </g>
          );
        })}
        {xTickIndices.map((i) => (
          <text key={"x" + i} x={toX(i)} y={H - 6} textAnchor="middle" fontSize={9} fill="rgb(var(--muted-foreground))" fontFamily="var(--font-mono)">{data[i].t}</text>
        ))}
        <path d={areaPath} fill={"url(#" + gradId + ")"} />
        <path d={linePath} fill="none" stroke={color} strokeWidth={1.8} strokeLinejoin="round" />
        {tooltip ? (
          <g>
            <line x1={tooltip.x} y1={padTop} x2={tooltip.x} y2={H - padBottom} stroke="rgb(var(--border))" strokeWidth={1} strokeDasharray="3 3" />
            <circle cx={tooltip.x} cy={tooltip.y} r={3.5} fill={color} />
          </g>
        ) : null}
      </svg>
      {tooltip ? (
        <div style={{ position: "absolute", top: "8px", left: "50%", transform: "translateX(-50%)", background: "rgb(var(--surface))", border: "1px solid rgb(var(--border))", borderRadius: "6px", padding: "4px 10px", pointerEvents: "none", whiteSpace: "nowrap" }}>
          <span style={{ fontSize: "11px", color: "rgb(var(--muted-foreground))", fontFamily: "var(--font-mono)" }}>{tooltip.point.t}</span>{" "}
          <span style={{ fontSize: "12px", color, fontFamily: "var(--font-mono)", fontWeight: 500 }}>{formatValue(tooltip.point.v)}</span>
        </div>
      ) : null}
    </div>
  );
}
