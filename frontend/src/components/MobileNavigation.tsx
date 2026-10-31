'use client';

import { useMobileSheet } from '@/hooks/useMobileSheet';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useState } from 'react';
import { Image, Sparkles, Activity, Menu, X } from 'lucide-react';
import { useAuth } from '@/contexts/AuthContext';
import { useTheme } from '@/contexts/ThemeContext';
import { useQuery } from '@tanstack/react-query';
import { foldersApi } from '@/lib/api';

export default function MobileNavigation() {
  const [open, setOpen] = useState(false);
  const pathname = usePathname();
  const sheet = useMobileSheet(open, () => setOpen(false));
  const { user, logout } = useAuth();
  const { theme, setTheme } = useTheme();
  const { data } = useQuery({ queryKey: ['folders', 'mobile'], queryFn: () => foldersApi.list({ limit: 200 }) });
  const links = [['Clusters', '/clusters'], ['Upload', '/upload'], ['Edit', '/images?tool=Edit'], ['Vision', '/images?tool=Ask%20Vision'], ['Models', '/models'], ['Billing', '/billing'], ['Settings', '/settings'], ...(user?.role === 'admin' ? [['Admin', '/admin'], ['Debug', '/debug']] : [])];
  return <>
    <nav aria-label="Mobile navigation" className="mobile-tabs md:hidden">
      {[
        { icon: Image, label: 'Library', href: '/images' },
        { icon: Sparkles, label: 'Create', href: '/images?tool=Create' },
        { icon: Activity, label: 'Jobs', href: '/jobs' },
      ].map(({ icon: Icon, label, href }) => (
        <Link key={label} href={href} aria-current={pathname === href ? 'page' : undefined} onClick={() => setOpen(false)} className="flex flex-col items-center justify-center gap-1 text-xs">
          <Icon size={20} />{label}
        </Link>
      ))}
      <button aria-expanded={open} onClick={() => setOpen(!open)} className="flex flex-col items-center justify-center gap-1 text-xs"><Menu size={20} />More</button>
    </nav>
    {open && <div className="fixed inset-0 z-50 md:hidden">
      <button aria-label="Close More menu" className="absolute inset-0 bg-foreground/30" onClick={() => setOpen(false)} />
      <section ref={sheet} role="dialog" aria-modal="true" aria-label="More" className="mobile-sheet absolute inset-x-0 bottom-0 max-h-[85dvh] overflow-auto rounded-t-2xl border border-border bg-background p-4" onKeyDown={e => e.key === 'Escape' && setOpen(false)}>
        <div className="flex items-center justify-between"><h2 className="font-semibold">More</h2><button autoFocus aria-label="Close More" onClick={() => setOpen(false)}><X /></button></div>
        <div className="grid grid-cols-2 gap-2 py-3">{links.map(([label, href]) => <Link key={label} href={href} onClick={() => setOpen(false)} className="flex items-center rounded-lg border border-border px-3 py-2 text-sm">{label}</Link>)}</div>
        <h3 className="py-2 text-sm font-medium">Folders</h3>
        {!data?.items.length && <p className="py-2 text-sm text-muted-foreground">No folders yet</p>}
        {data?.items.map(folder => <Link key={folder.id} href={`/images/folder/${folder.id}`} onClick={() => setOpen(false)} className="flex items-center truncate border-b border-border text-sm">{folder.name}</Link>)}
        <label className="flex items-center justify-between py-3">Theme<select aria-label="Theme" value={theme} onChange={e => setTheme(e.target.value as 'light' | 'dark' | 'auto')} className="rounded border border-border px-3"><option value="light">Light</option><option value="dark">Dark</option><option value="auto">Auto</option></select></label>
        <button onClick={() => { logout(); setOpen(false); }} className="w-full rounded-lg border border-border">Log out</button>
      </section>
    </div>}
  </>;
}
