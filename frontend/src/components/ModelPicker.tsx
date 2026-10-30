'use client';

import { useState } from 'react';

export interface PickerModel {
  id: string;
  label: string;
  provider: string;
  cost?: number;
}

export default function ModelPicker({
  models,
  value,
  onChange,
}: {
  models: PickerModel[];
  value: string;
  onChange: (id: string) => void;
}) {
  const [search, setSearch] = useState('');
  const groups = Array.from(new Set(models.map((m) => m.provider)));
  return (
    <div className="space-y-2">
      <input
        aria-label="Search models"
        placeholder="Search models…"
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
      />
      <select
        aria-label="Model"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full rounded-md border border-input bg-background px-2 py-2 text-sm"
      >
        <option value="" disabled>
          Select model
        </option>
        {groups.map((group) => (
          <optgroup key={group} label={group}>
            {models
              .filter(
                (m) =>
                  m.provider === group &&
                  (m.id === value || `${m.label} ${m.provider}`.toLowerCase().includes(search.toLowerCase()))
              )
              .map((m) => (
                <option key={m.id} value={m.id}>
                  {m.label}
                  {m.cost != null ? ` · ${m.cost} sparks/image` : ''}
                </option>
              ))}
          </optgroup>
        ))}
      </select>
    </div>
  );
}
