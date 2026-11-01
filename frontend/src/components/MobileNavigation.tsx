'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';

const tabs = [
  { label: 'Collection', href: '/collection', paths: ['/collection', '/images', '/clusters', '/folders', '/upload'], icon: <><path d="M4 5h16v14H4z" /><path d="M4 15l5-4 4 3 3-2 4 3" /><circle cx="9" cy="9" r="1.3" /></> },
  { label: 'Studio', href: '/studio', paths: ['/studio', '/models'], icon: <><path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z" /><path d="M18.5 16v4M16.5 18h4" /></> },
  { label: 'Account', href: '/account', paths: ['/account', '/billing', '/jobs', '/notifications', '/settings', '/admin', '/debug'], icon: <><circle cx="12" cy="8.5" r="3.5" /><path d="M5 20c1-3.6 3.6-5.5 7-5.5s6 1.9 7 5.5" /></> },
];

export default function MobileNavigation() {
  const pathname = usePathname();
  return (
    <nav aria-label="Mobile navigation" className="mobile-tabs md:hidden">
      {tabs.map(tab => (
        <Link key={tab.href} href={tab.href} aria-current={tab.paths.some(path => pathname === path || pathname.startsWith(`${path}/`)) ? 'page' : undefined} className="flex flex-col items-center justify-center gap-1 text-xs">
          <svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            {tab.icon}
          </svg>
          {tab.label}
        </Link>
      ))}
    </nav>
  );
}
