import { useSyncExternalStore } from 'react';

// Images hide as soon as the user confirms, before the background job finishes.
let deleting: ReadonlySet<number> = new Set();
const listeners = new Set<() => void>();

function publish(next: ReadonlySet<number>) {
  deleting = next;
  listeners.forEach(listener => listener());
}

export const markDeleting = (ids: number[]) => publish(new Set([...Array.from(deleting), ...ids]));
export const clearDeleting = () => publish(new Set());

export function useDeletingImages() {
  return useSyncExternalStore(
    listener => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    () => deleting,
    () => deleting,
  );
}
