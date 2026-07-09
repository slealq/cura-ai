'use client';

import Link from 'next/link';
import {
  FolderOpen,
  Sparkles,
  Pencil,
  Eye,
  Box,
  Search,
} from 'lucide-react';
import MarketingShell from '@/components/marketing/MarketingShell';

const features = [
  {
    icon: FolderOpen,
    title: 'Organize at scale',
    description:
      'Upload thousands of images. SightLab tags, describes, and clusters them automatically so your library organizes itself.',
  },
  {
    icon: Search,
    title: 'Semantic search',
    description:
      'Find any image by describing it. Hybrid semantic + text search understands what is in your images, not just filenames.',
  },
  {
    icon: Box,
    title: 'Train custom models',
    description:
      'Turn any folder or cluster into a custom LoRA model. Built-in evaluation measures how faithfully it reproduces your style.',
  },
  {
    icon: Sparkles,
    title: 'Generate images',
    description:
      'Generate with state-of-the-art models — FLUX, Qwen, Nano Banana — using up to two of your custom styles per prompt.',
  },
  {
    icon: Pencil,
    title: 'Edit with AI',
    description:
      'Six editing models for image-to-image transformation, restyling, and face swap — all from one workspace.',
  },
  {
    icon: Eye,
    title: 'Vision analysis',
    description:
      'Ask questions about any image. Tag, describe, or run custom prompts with top vision models, with full history.',
  },
];

const steps = [
  { n: '1', title: 'Upload', text: 'Drop in your image library. Processing starts automatically.' },
  { n: '2', title: 'Train', text: 'Pick a folder or cluster and train a custom style model in minutes.' },
  { n: '3', title: 'Create', text: 'Generate and edit new images in your style, ready to download.' },
];

export default function LandingPage() {
  return (
    <MarketingShell>
      {/* Hero */}
      <section className="relative overflow-hidden">
        <div
          className="pointer-events-none absolute inset-0 opacity-30"
          style={{
            background:
              'radial-gradient(60% 50% at 50% 0%, hsl(262 83% 58% / 0.25) 0%, transparent 70%)',
          }}
        />
        <div className="mx-auto max-w-6xl px-6 pt-24 pb-20 text-center">
          <h1 className="text-4xl sm:text-6xl font-bold tracking-tight leading-tight">
            Your images, understood.
            <br />
            <span className="bg-gradient-to-r from-violet-500 via-blue-500 to-emerald-500 bg-clip-text text-transparent">
              Your style, generated.
            </span>
          </h1>
          <p className="mx-auto mt-6 max-w-2xl text-lg text-muted-foreground">
            SightLab is an AI image studio: organize and search your visual library,
            train models on your own style, and generate new images that look like you made them.
          </p>
          <div className="mt-10 flex items-center justify-center gap-4">
            <Link
              href="/login?mode=signup"
              className="rounded-full bg-primary px-8 py-3 text-primary-foreground font-medium hover:opacity-90 transition-opacity"
            >
              Start creating
            </Link>
            <Link
              href="/pricing"
              className="rounded-full border border-border px-8 py-3 font-medium hover:bg-secondary transition-colors"
            >
              View pricing
            </Link>
          </div>
        </div>
      </section>

      {/* Features */}
      <section className="mx-auto max-w-6xl px-6 py-20">
        <h2 className="text-center text-3xl font-bold tracking-tight">
          Everything between upload and final image
        </h2>
        <div className="mt-12 grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
          {features.map((f) => (
            <div
              key={f.title}
              className="rounded-2xl border border-border bg-card p-6 hover:shadow-md transition-shadow"
            >
              <f.icon className="h-8 w-8 text-violet-500" />
              <h3 className="mt-4 text-lg font-semibold">{f.title}</h3>
              <p className="mt-2 text-sm text-muted-foreground leading-relaxed">{f.description}</p>
            </div>
          ))}
        </div>
      </section>

      {/* How it works */}
      <section className="border-t border-border bg-secondary/30">
        <div className="mx-auto max-w-6xl px-6 py-20">
          <h2 className="text-center text-3xl font-bold tracking-tight">How it works</h2>
          <div className="mt-12 grid gap-8 sm:grid-cols-3">
            {steps.map((s) => (
              <div key={s.n} className="text-center">
                <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-gradient-to-br from-violet-500 to-blue-500 text-white text-lg font-bold">
                  {s.n}
                </div>
                <h3 className="mt-4 text-lg font-semibold">{s.title}</h3>
                <p className="mt-2 text-sm text-muted-foreground">{s.text}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* CTA */}
      <section className="mx-auto max-w-6xl px-6 py-24 text-center">
        <h2 className="text-3xl font-bold tracking-tight">Ready to build your visual AI studio?</h2>
        <p className="mt-4 text-muted-foreground">
          Sign up free, explore your library, and pay only for what you create with spark credits.
        </p>
        <Link
          href="/login?mode=signup"
          className="mt-8 inline-block rounded-full bg-primary px-8 py-3 text-primary-foreground font-medium hover:opacity-90 transition-opacity"
        >
          Get started
        </Link>
      </section>
    </MarketingShell>
  );
}
