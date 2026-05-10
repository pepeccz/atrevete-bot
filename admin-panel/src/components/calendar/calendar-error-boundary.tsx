"use client";

import { Component, type ReactNode, type ErrorInfo } from "react";

interface Props {
  children: ReactNode;
  onResetToWeek?: () => void;
}

interface State {
  hasError: boolean;
  errorMessage: string | null;
}

/**
 * CalendarErrorBoundary — class component wrapping the calendar tree.
 *
 * On any unhandled render error:
 *   - Logs error to console (no external sink in this version)
 *   - Shows a friendly Spanish fallback with a "Volver a Semana" button
 *
 * The `onResetToWeek` prop lets the parent switch the view back to 'week'
 * and unmount the day-view component that caused the error.
 */
export class CalendarErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false, errorMessage: null };
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, errorMessage: error.message ?? "Error desconocido" };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error("[CalendarErrorBoundary] Uncaught error in calendar tree:", error, info);
  }

  handleReset = (): void => {
    this.setState({ hasError: false, errorMessage: null });
    this.props.onResetToWeek?.();
  };

  render(): ReactNode {
    if (this.state.hasError) {
      return (
        <div className="flex flex-col items-center justify-center gap-4 py-16 px-4 text-center rounded-[14px] border border-line bg-white">
          <div className="text-[40px]" role="img" aria-label="Error">⚠️</div>
          <p className="text-sm font-medium text-ink max-w-xs">
            No se pudo cargar el calendario. Recargá la página.
          </p>
          {this.state.errorMessage && (
            <p className="text-xs text-ink-mute max-w-xs font-mono">
              {this.state.errorMessage}
            </p>
          )}
          <button
            onClick={this.handleReset}
            className="mt-2 px-4 py-2 rounded-[10px] bg-gold-soft text-gold-dark text-sm font-semibold hover:bg-gold-line transition-colors"
          >
            Volver a Semana
          </button>
        </div>
      );
    }

    return this.props.children;
  }
}
