'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { Search, RefreshCw } from 'lucide-react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { imagesApi, clustersApi } from '@/lib/api';
import { cn, getStatusColor } from '@/lib/utils';

export default function Header() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const [searchQuery, setSearchQuery] = useState('');

  const { data: stats } = useQuery({
    queryKey: ['stats'],
    queryFn: imagesApi.getStats,
    refetchInterval: 10000,
  });

  const reclusterMutation = useMutation({
    mutationFn: () => clustersApi.recluster(),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['clusters'] });
      queryClient.invalidateQueries({ queryKey: ['stats'] });
    },
  });

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    if (searchQuery.trim()) {
      router.push(`/search?q=${encodeURIComponent(searchQuery.trim())}`);
    }
  };

  return (
    <header className="h-16 bg-white border-b border-border flex items-center justify-between px-6">
      <form onSubmit={handleSearch} className="flex-1 max-w-xl">
        <div className="relative">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <input
            type="text"
            placeholder="Search images by description..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full pl-10 pr-4 py-2 border border-border rounded-lg bg-muted/50 focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary"
          />
        </div>
      </form>

      <div className="flex items-center gap-4 ml-6">
        {stats && (
          <div className="flex items-center gap-3 text-sm">
            <div className="flex items-center gap-1">
              <span className="text-muted-foreground">Images:</span>
              <span className="font-medium">{stats.total_images}</span>
            </div>
            <div className="flex items-center gap-1">
              <span className="text-muted-foreground">Clusters:</span>
              <span className="font-medium">{stats.total_clusters}</span>
            </div>
            {stats.pending > 0 && (
              <span className={cn('px-2 py-0.5 rounded-full text-xs', getStatusColor('pending'))}>
                {stats.pending} processing
              </span>
            )}
            {stats.failed > 0 && (
              <span className={cn('px-2 py-0.5 rounded-full text-xs', getStatusColor('failed'))}>
                {stats.failed} failed
              </span>
            )}
          </div>
        )}

        <button
          onClick={() => reclusterMutation.mutate()}
          disabled={reclusterMutation.isPending}
          className={cn(
            'flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-colors',
            'bg-primary text-primary-foreground hover:bg-primary/90',
            'disabled:opacity-50 disabled:cursor-not-allowed'
          )}
        >
          <RefreshCw
            className={cn('h-4 w-4', reclusterMutation.isPending && 'animate-spin')}
          />
          Recluster
        </button>
      </div>
    </header>
  );
}
