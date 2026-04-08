"use client";

import { useState, useEffect, useCallback, useRef } from "react";

export interface UseApiQueryResult<T> {
  data: T | null;
  isLoading: boolean;
  error: Error | null;
  refetch: () => void;
}

/**
 * Hook genérico para llamadas a la API con gestión automática de estado,
 * cancelación mediante AbortController, y función `refetch`.
 *
 * Cancela la petición en curso cuando cambian las dependencias o al desmontar.
 *
 * @param fetcher  Función que recibe un `AbortSignal` y devuelve una `Promise<T>`
 * @param deps     Array de dependencias que disparan una nueva petición
 * @returns        `{ data, isLoading, error, refetch }`
 *
 * @example
 * const { data, isLoading, error } = useApiQuery(
 *   (signal) => api.getCustomers(signal),
 *   []
 * );
 */
export function useApiQuery<T>(
  fetcher: (signal: AbortSignal) => Promise<T>,
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  deps: any[]
): UseApiQueryResult<T> {
  const [data, setData] = useState<T | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [error, setError] = useState<Error | null>(null);
  const [refetchTrigger, setRefetchTrigger] = useState<number>(0);

  // Ref para mantener el fetcher actualizado sin re-ejecutar el effect
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;

  const refetch = useCallback(() => {
    setRefetchTrigger((prev) => prev + 1);
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    const { signal } = controller;

    setIsLoading(true);
    setError(null);

    const run = async () => {
      try {
        const result = await fetcherRef.current(signal);
        if (!signal.aborted) {
          setData(result);
        }
      } catch (err) {
        if (signal.aborted) {
          // Petición cancelada — no actualizar estado
          return;
        }
        setError(err instanceof Error ? err : new Error(String(err)));
      } finally {
        if (!signal.aborted) {
          setIsLoading(false);
        }
      }
    };

    run();

    return () => {
      controller.abort();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, refetchTrigger]);

  return { data, isLoading, error, refetch };
}
