'use client';

import Link from 'next/link';
import { Zap, Check } from 'lucide-react';
import MarketingShell from '@/components/marketing/MarketingShell';

const packs = [
  { name: 'Starter', price: 10, sparks: 5000, bonus: 2000 },
  { name: 'Creator', price: 25, sparks: 15000, bonus: 7000, highlight: true },
  { name: 'Pro', price: 50, sparks: 35000, bonus: 13000 },
  { name: 'Studio', price: 100, sparks: 70000, bonus: 35000 },
];

const plans = [
  {
    name: 'Hobby',
    price: 15,
    sparks: 15000,
    blurb: 'For exploring and light creative work.',
  },
  {
    name: 'Pro',
    price: 40,
    sparks: 45000,
    blurb: 'For creators generating and training regularly.',
    highlight: true,
  },
  {
    name: 'Studio',
    price: 80,
    sparks: 100000,
    blurb: 'For heavy pipelines and team-scale output.',
  },
];

const examples = [
  { activity: 'Process 100 images (tag + describe + search index)', sparks: '~1,500' },
  { activity: 'Generate 20 images (FLUX dev)', sparks: '~1,000' },
  { activity: 'Generate 20 images (Nano Banana Pro)', sparks: '~1,560' },
  { activity: 'Edit 10 images (Qwen Image Max)', sparks: '~1,500' },
  { activity: 'Train 1 custom style model', sparks: '~4,000' },
];

function fmt(n: number) {
  return n.toLocaleString('en-US');
}

export default function PricingPage() {
  return (
    <MarketingShell>
      <section className="mx-auto max-w-6xl px-6 pt-20 pb-12 text-center">
        <h1 className="text-4xl sm:text-5xl font-bold tracking-tight">Simple, usage-based pricing</h1>
        <p className="mx-auto mt-4 max-w-2xl text-lg text-muted-foreground">
          Everything runs on <span className="font-medium text-foreground">sparks</span> — one credit
          currency for processing, generation, editing, and training. Buy packs as you go, or
          subscribe for the best rate.
        </p>
      </section>

      {/* Subscriptions */}
      <section className="mx-auto max-w-6xl px-6 py-8">
        <h2 className="text-center text-2xl font-bold tracking-tight">Monthly subscriptions</h2>
        <p className="mt-2 text-center text-sm text-muted-foreground">Best value — sparks refresh every month. Cancel anytime.</p>
        <div className="mt-10 grid gap-6 sm:grid-cols-3">
          {plans.map((p) => (
            <div
              key={p.name}
              className={`relative rounded-2xl border p-8 flex flex-col ${
                p.highlight ? 'border-violet-500 shadow-lg' : 'border-border'
              }`}
            >
              {p.highlight && (
                <span className="absolute -top-3 left-1/2 -translate-x-1/2 rounded-full bg-violet-500 px-3 py-0.5 text-xs font-medium text-white">
                  Most popular
                </span>
              )}
              <h3 className="text-lg font-semibold">{p.name}</h3>
              <div className="mt-3 flex items-baseline gap-1">
                <span className="text-4xl font-bold">${p.price}</span>
                <span className="text-muted-foreground">/month</span>
              </div>
              <div className="mt-4 flex items-center gap-2 text-sm">
                <Zap className="h-4 w-4 text-amber-500" />
                <span className="font-medium">{fmt(p.sparks)} sparks / month</span>
              </div>
              <p className="mt-3 text-sm text-muted-foreground flex-1">{p.blurb}</p>
              <Link
                href="/login?mode=signup"
                className={`mt-6 rounded-full px-6 py-2.5 text-center text-sm font-medium transition-opacity ${
                  p.highlight
                    ? 'bg-primary text-primary-foreground hover:opacity-90'
                    : 'border border-border hover:bg-secondary'
                }`}
              >
                Get started
              </Link>
            </div>
          ))}
        </div>
      </section>

      {/* Packs */}
      <section className="mx-auto max-w-6xl px-6 py-12">
        <h2 className="text-center text-2xl font-bold tracking-tight">One-time spark packs</h2>
        <p className="mt-2 text-center text-sm text-muted-foreground">No commitment — buy sparks whenever you need them.</p>
        <div className="mt-10 grid gap-6 sm:grid-cols-2 lg:grid-cols-4">
          {packs.map((p) => (
            <div
              key={p.name}
              className={`rounded-2xl border p-6 text-center ${
                p.highlight ? 'border-violet-500 shadow-lg' : 'border-border'
              }`}
            >
              <h3 className="font-semibold">{p.name}</h3>
              <div className="mt-2 text-3xl font-bold">${p.price}</div>
              <div className="mt-3 text-sm">
                <span className="font-medium">{fmt(p.sparks + p.bonus)} sparks</span>
              </div>
              <div className="mt-1 text-xs text-muted-foreground">
                {fmt(p.sparks)} + {fmt(p.bonus)} bonus
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* What sparks buy */}
      <section className="border-t border-border bg-secondary/30">
        <div className="mx-auto max-w-3xl px-6 py-16">
          <h2 className="text-center text-2xl font-bold tracking-tight">What sparks get you</h2>
          <div className="mt-8 divide-y divide-border rounded-2xl border border-border bg-card">
            {examples.map((e) => (
              <div key={e.activity} className="flex items-center justify-between gap-4 px-6 py-4 text-sm">
                <div className="flex items-center gap-3">
                  <Check className="h-4 w-4 shrink-0 text-emerald-500" />
                  <span>{e.activity}</span>
                </div>
                <span className="whitespace-nowrap font-medium">{e.sparks}</span>
              </div>
            ))}
          </div>
          <p className="mt-6 text-center text-xs text-muted-foreground">
            Costs vary with model choice and image size — exact estimates are shown in-app before
            every operation. Unused pack sparks never expire.
          </p>
        </div>
      </section>

      {/* CTA */}
      <section className="mx-auto max-w-6xl px-6 py-20 text-center">
        <h2 className="text-2xl font-bold tracking-tight">Questions about pricing?</h2>
        <p className="mt-3 text-muted-foreground">
          Reach out at{' '}
          <a href="mailto:stuart.leal23@gmail.com" className="underline hover:text-foreground">
            stuart.leal23@gmail.com
          </a>{' '}
          — we are happy to help you pick the right plan.
        </p>
      </section>
    </MarketingShell>
  );
}
