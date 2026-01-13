'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import {
  LayoutGrid,
  Image as ImageIcon,
  Folder,
  Settings,
  Activity,
  Upload,
} from 'lucide-react';
import { cn } from '@/lib/utils';

const navigation = [
  { name: 'Clusters', href: '/', icon: LayoutGrid },
  { name: 'All Images', href: '/images', icon: ImageIcon },
  { name: 'Upload', href: '/upload', icon: Upload },
  { name: 'Jobs', href: '/jobs', icon: Activity },
  { name: 'Settings', href: '/settings', icon: Settings },
];

export default function Sidebar() {
  const pathname = usePathname();

  return (
    <aside className="w-64 bg-white border-r border-border flex flex-col">
      <div className="p-6 border-b border-border">
        <Link href="/" className="flex items-center gap-2">
          <Folder className="h-8 w-8 text-primary" />
          <div>
            <h1 className="font-semibold text-lg">Design Pipeline</h1>
            <p className="text-xs text-muted-foreground">Idea Ingestion</p>
          </div>
        </Link>
      </div>

      <nav className="flex-1 p-4 space-y-1">
        {navigation.map((item) => {
          const isActive =
            pathname === item.href ||
            (item.href !== '/' && pathname.startsWith(item.href));

          return (
            <Link
              key={item.name}
              href={item.href}
              className={cn(
                'flex items-center gap-3 px-3 py-2 rounded-lg text-sm font-medium transition-colors',
                isActive
                  ? 'bg-primary text-primary-foreground'
                  : 'text-muted-foreground hover:bg-muted hover:text-foreground'
              )}
            >
              <item.icon className="h-5 w-5" />
              {item.name}
            </Link>
          );
        })}
      </nav>

      <div className="p-4 border-t border-border">
        <div className="text-xs text-muted-foreground">
          <p>Design Idea Pipeline v0.1.0</p>
        </div>
      </div>
    </aside>
  );
}
