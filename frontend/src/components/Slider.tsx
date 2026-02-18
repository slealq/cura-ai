"use client";

import React from "react";

interface SliderProps {
  min: number;
  max: number;
  step?: number;
  value: number;
  onChange: (value: number) => void;
  className?: string;
  disabled?: boolean;
}

export function Slider({
  min,
  max,
  step,
  value,
  onChange,
  className = "",
  disabled,
}: SliderProps) {
  const pct = max > min ? ((value - min) / (max - min)) * 100 : 0;

  return (
    <input
      type="range"
      min={min}
      max={max}
      step={step}
      value={value}
      disabled={disabled}
      onChange={(e) => onChange(parseFloat(e.target.value))}
      className={className}
      style={{ "--slider-pct": `${pct}%` } as React.CSSProperties}
    />
  );
}
