"use client";

import { Component, ReactNode } from "react";

/**
 * Tiny error boundary for SignalCard. When the terse renderer throws
 * for any reason, the boundary swallows the error and the parent
 * falls back to the verbose body. This is layer 1 of the four-layer
 * safety - "fail open at render time."
 */
export class SignalErrorBoundary extends Component<
  { children: ReactNode; onError: () => void },
  { hasError: boolean }
> {
  constructor(props: { children: ReactNode; onError: () => void }) {
    super(props);
    this.state = { hasError: false };
  }
  static getDerivedStateFromError() {
    return { hasError: true };
  }
  componentDidCatch() {
    this.props.onError();
  }
  render() {
    if (this.state.hasError) return null;
    return this.props.children;
  }
}
