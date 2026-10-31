'use client';

import { useEffect, type ReactNode } from 'react';
import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';

type Tool = 'generate' | 'edit' | 'vision';

const entries = {
  generate: {
    title: 'Create in your library',
    hint: 'Create images with the right inspector. Your results appear alongside the rest of your library.',
    label: 'Open Create',
    href: '/images?tool=Create',
    advanced: 'Advanced creation',
    detail: 'Use advanced creation for two-LoRA composition, prompt expansion, seeds, and model-specific controls.',
  },
  edit: {
    title: 'Edit in your library',
    hint: 'Select images in the library, then choose Edit in the right inspector.',
    label: 'Select library images',
    href: '/images?tool=Edit',
    advanced: 'Upload sources & advanced editing',
    detail: 'Upload, paste, or drop source files; mix library and generated sources; use model-specific controls and browse edit history.',
  },
  vision: {
    title: 'Ask Vision in your library',
    hint: 'Select images in the library, then choose Ask Vision in the right inspector.',
    label: 'Select library images',
    href: '/images?tool=Ask%20Vision',
    advanced: 'Upload a file & view analysis history',
    detail: 'Analyze an uploaded file, use Tag or Describe mode, adjust analysis settings, and browse or manage saved results.',
  },
} satisfies Record<Tool, { title: string; hint: string; label: string; href: string; advanced: string; detail: string }>;

// Keep specialized workflows mounted only when explicitly requested. Existing
// LoRA/prompt links retain their full generator semantics for backwards compatibility.
export default function ToolEntry({ tool, children }: { tool: Tool; children: ReactNode }) {
  const params = useSearchParams();
  const router = useRouter();
  const advanced = params.get('advanced') === '1' || (tool === 'generate' && (params.has('lora') || params.has('prompt')));
  const entry = entries[tool];
  useEffect(() => {
    if (tool === 'generate' && !advanced) router.replace(entry.href);
  }, [tool, advanced, router, entry.href]);

  if (advanced) return (
    <div className="space-y-4">
      <Link href={entry.href} className="inline-block text-sm text-muted-foreground hover:text-foreground hover:underline">← {tool === 'generate' ? 'Create in library' : 'Select images in library'}</Link>
      {children}
    </div>
  );

  return (
    <div className="mx-auto w-full max-w-[880px] space-y-5">
      <h1 className="text-xl font-semibold tracking-tight">{entry.title}</h1>
      <section className="space-y-4 rounded-lg border border-border bg-background p-5">
        <p className="text-sm text-muted-foreground">{entry.hint}</p>
        <Link href={entry.href} className="inline-flex rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-foreground hover:opacity-90">{entry.label}</Link>
      </section>
      <section className="space-y-3 rounded-lg border border-border bg-chrome p-5">
        <h2 className="text-sm font-medium">{entry.advanced}</h2>
        <p className="text-sm text-muted-foreground">{entry.detail}</p>
        <Link href={`/${tool}?advanced=1`} className="inline-flex rounded-md border border-input bg-background px-3 py-2 text-sm hover:bg-accent">{entry.advanced}</Link>
      </section>
    </div>
  );
}
