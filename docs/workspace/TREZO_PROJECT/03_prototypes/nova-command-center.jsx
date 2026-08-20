import { useState } from "react";

// ── PALETTE ──────────────────────────────────────────────────────────────────
const C = {
  bg:       "#07080a",
  surface:  "#0e1015",
  card:     "#13161c",
  border:   "#1e2330",
  accent:   "#00c9a7",
  gold:     "#f5a623",
  blue:     "#4da6ff",
  red:      "#ff4d6d",
  purple:   "#b57bee",
  text:     "#dde3f0",
  muted:    "#5c6480",
  dim:      "#2a2f3e",
};

// ── SHARED ────────────────────────────────────────────────────────────────────
const mono = "'JetBrains Mono', 'Fira Code', monospace";

const Badge = ({ color, children, sm }) => (
  <span style={{
    background: color + "22", color, border: `1px solid ${color}44`,
    borderRadius: 4, padding: sm ? "1px 6px" : "3px 9px",
    fontSize: sm ? 