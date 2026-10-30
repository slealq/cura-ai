import { useQuery } from '@tanstack/react-query';
import { settingsApi } from '@/lib/api';

export function useModelCatalog() {
  return useQuery({ queryKey: ['model-catalog'], queryFn: settingsApi.getModelCatalog, staleTime: 5 * 60 * 1000 });
}
