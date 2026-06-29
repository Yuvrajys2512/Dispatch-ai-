import { Component, type ReactNode } from "react";

interface Props {
  children: ReactNode;
}

interface State {
  error: Error | null;
}

/**
 * Top-level error boundary: catches render crashes and shows a recovery screen
 * instead of a blank page. A supervisor refresh or the retry button resets it.
 */
export class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  private handleRetry = () => {
    this.setState({ error: null });
  };

  render() {
    if (this.state.error) {
      return (
        <div className="flex min-h-screen flex-col items-center justify-center gap-4 bg-neutral-950 text-neutral-100">
          <p className="text-lg font-semibold text-red-400">Dashboard error</p>
          <p className="max-w-sm text-center text-sm text-neutral-500">
            {this.state.error.message}
          </p>
          <button
            type="button"
            onClick={this.handleRetry}
            className="rounded bg-neutral-800 px-4 py-2 text-sm text-neutral-300 hover:bg-neutral-700"
          >
            Retry
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
