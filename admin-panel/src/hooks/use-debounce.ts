"use client";

import { useState, useEffect } from "react";

/**
 * Retrasa la actualización de un valor hasta que transcurra `delay` ms
 * sin nuevas actualizaciones. Útil para evitar llamadas API en cada
 * pulsación de tecla.
 *
 * @param value  Valor a debouncer
 * @param delay  Tiempo de espera en milisegundos
 * @returns      El valor debounced
 */
export function useDebounce<T>(value: T, delay: number): T {
  const [debouncedValue, setDebouncedValue] = useState<T>(value);

  useEffect(() => {
    const handler = setTimeout(() => {
      setDebouncedValue(value);
    }, delay);

    return () => {
      clearTimeout(handler);
    };
  }, [value, delay]);

  return debouncedValue;
}
