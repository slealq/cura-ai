'use client';

import { useState, useEffect, Suspense } from 'react';
import { useSearchParams } from 'next/navigation';
import { useQuery } from '@tanstack/react-query';
import { Loader2, Search } from 'lucide-react';
import { searchApi } from '@/lib/api';
import ImageCard from '@/components/ImageCard';
import ImageDrawer from '@/components/ImageDrawer';
import type { Image } from '@/types';

function SearchContent() {
  const searchParams = useSearchParams();
  const initialQuery = searchParams.get('q') || '';
  const [query, setQuery] = useState(initialQuery);
  const [searchTerm, setSearchTerm] = useState(initialQuery);
  const [selectedImage, setSelectedImage] = useState<Image | null>(null);

  // Update search when URL changes
  useEffect(() => {
    const q = searchParams.get('q') || '';
    setQuery(q);
    setSearchTerm(q);
  }, [searchParams]);

  const { data: results, isLoading } = useQuery({
    queryKey: ['search', searchTerm],
    queryFn: () => searchApi.semantic(searchTerm, 50),
    enabled: searchTerm.length > 0,
  });

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    setSearchTerm(query);
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Search</h1>
        <p className="text-muted-foreground mt-1">
          Search images by description using semantic similarity
        </p>
      </div>

      {/* Search Form */}
      <form onSubmit={handleSearch} className="flex gap-2">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-5 w-5 text-muted-foreground" />
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search for design styles, colors, moods..."
            className="w-full pl-10 pr-4 py-3 border border-border rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary"
          />
        </div>
        <button
          type="submit"
          className="px-6 py-3 bg-primary text-primary-foreground rounded-lg font-medium hover:bg-primary/90 transition-colors"
        >
          Search
        </button>
      </form>

      {/* Results */}
      {isLoading ? (
        <div className="flex items-center justify-center h-64">
          <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
        </div>
      ) : results ? (
        <div className="space-y-4">
          <p className="text-sm text-muted-foreground">
            Found {results.total} results for "{results.query}"
          </p>

          {results.results.length > 0 ? (
            <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 gap-4">
              {results.results.map((r) => (
                <ImageCard
                  key={r.image.id}
                  image={r.image}
                  score={r.score}
                  onClick={() => setSelectedImage(r.image)}
                />
              ))}
            </div>
          ) : (
            <div className="flex items-center justify-center h-64 text-center">
              <p className="text-muted-foreground">
                No images found matching your search
              </p>
            </div>
          )}
        </div>
      ) : searchTerm ? null : (
        <div className="flex flex-col items-center justify-center h-64 text-center">
          <Search className="h-12 w-12 text-muted-foreground/50 mb-4" />
          <p className="text-muted-foreground">
            Enter a search term to find similar images
          </p>
          <p className="text-sm text-muted-foreground mt-2">
            Try "minimal product photography" or "warm earthy tones"
          </p>
        </div>
      )}

      {selectedImage && (
        <ImageDrawer
          image={selectedImage}
          onClose={() => setSelectedImage(null)}
        />
      )}
    </div>
  );
}

export default function SearchPage() {
  return (
    <Suspense
      fallback={
        <div className="flex items-center justify-center h-64">
          <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
        </div>
      }
    >
      <SearchContent />
    </Suspense>
  );
}
