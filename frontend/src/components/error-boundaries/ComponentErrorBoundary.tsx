'use client';

import React, { Component, ReactNode } from 'react';
import { Button } from '@/components/ui/button';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { AlertCircle, RefreshCw, Eye, EyeOff } from 'lucide-react';

interface Props {
  children: ReactNode;
  componentName?: string;
  fallback?: ReactNode;
  showErrorDetails?: boolean;
  onError?: (error: Error, errorInfo: React.ErrorInfo) => void;
  onRetry?: () => void;
}

interface State {
  hasError: boolean;
  error: Error | null;
  errorInfo: React.ErrorInfo | null;
  errorId: string | null;
  retryCount: number;
  showDetails: boolean;
}

/**
 * Component-level error boundary for individual React components
 * Provides minimal UI disruption with inline error display
 */
export class ComponentErrorBoundary extends Component<Props, State> {
  private retryTimeout: NodeJS.Timeout | null = null;

  constructor(props: Props) {
    super(props);
    this.state = {
      hasError: false,
      error: null,
      errorInfo: null,
      errorId: null,
      retryCount: 0,
      showDetails: false,
    };
  }

  static getDerivedStateFromError(error: Error): Partial<State> {
    const errorId = `component-error-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;
    
    return {
      hasError: true,
      error,
      errorId,
    };
  }

  componentDidCatch(error: Error, errorInfo: React.ErrorInfo) {
    const componentName = this.props.componentName || 'Unknown Component';
    console.error(`Component Error Boundary (${componentName}) caught an error:`, error, errorInfo);
    
    this.setState({
      errorInfo,
    });

    // Report error with component context
    this.reportError(error, errorInfo);
    
    // Call custom error handler
    this.props.onError?.(error, errorInfo);
    
    // Auto-retry for transient errors
    this.scheduleAutoRetry(error);
  }

  componentWillUnmount() {
    if (this.retryTimeout) {
      clearTimeout(this.retryTimeout);
    }
  }

  private reportError = (error: Error, errorInfo: React.ErrorInfo) => {
    try {
      if (typeof window !== 'undefined') {
        // Report to monitoring with component context
        if ((window as any).posthog) {
          (window as any).posthog.capture('component_error_boundary_triggered', {
            component_name: this.props.componentName || 'unknown',
            error_message: error.message,
            error_stack: error.stack,
            component_stack: errorInfo.componentStack,
            error_id: this.state.errorId,
            retry_count: this.state.retryCount,
            url: window.location.href,
          });
        }
        
        if ((window as any).Sentry) {
          (window as any).Sentry.withScope((scope: any) => {
            scope.setTag('error_boundary', 'component');
            scope.setTag('component_name', this.props.componentName || 'unknown');
            scope.setContext('errorInfo', errorInfo);
            scope.setContext('errorId', this.state.errorId);
            (window as any).Sentry.captureException(error);
          });
        }
      }
    } catch (reportingError) {
      console.error('Failed to report component error:', reportingError);
    }
  };

  private scheduleAutoRetry = (error: Error) => {
    const isTransient = this.isTransientError(error);
    
    if (isTransient && this.state.retryCount < 1) {
      const retryDelay = 1000; // Quick retry for component errors
      
      this.retryTimeout = setTimeout(() => {
        this.handleRetry();
      }, retryDelay);
    }
  };

  private isTransientError = (error: Error): boolean => {
    const transientPatterns = [
      /network/i,
      /fetch/i,
      /loading/i,
      /timeout/i,
      /suspended/i,
      /chunk/i,
      /dynamic import/i,
      /hydration/i,
    ];
    
    return transientPatterns.some(pattern => 
      pattern.test(error.message) || pattern.test(error.name)
    );
  };

  private handleRetry = () => {
    const componentName = this.props.componentName || 'component';
    console.log(`Attempting to recover ${componentName}...`);
    
    this.setState(prevState => ({
      hasError: false,
      error: null,
      errorInfo: null,
      retryCount: prevState.retryCount + 1,
      showDetails: false,
    }));
    
    // Call custom retry handler
    this.props.onRetry?.();
  };

  private toggleDetails = () => {
    this.setState(prevState => ({
      showDetails: !prevState.showDetails,
    }));
  };

  private getErrorDisplayMessage = (error: Error): string => {
    const componentName = this.props.componentName || 'component';
    
    if (this.isTransientError(error)) {
      return `${componentName} is temporarily unavailable`;
    }
    
    // Check for specific error types
    if (error.message.includes('unauthorized') || error.message.includes('forbidden')) {
      return `${componentName} access denied`;
    }
    
    if (error.message.includes('not found') || error.message.includes('404')) {
      return `${componentName} content not found`;
    }
    
    if (error.message.includes('network') || error.message.includes('fetch')) {
      return `${componentName} connection failed`;
    }
    
    return `${componentName} encountered an error`;
  };

  render() {
    if (this.state.hasError) {
      // Use custom fallback if provided
      if (this.props.fallback) {
        return this.props.fallback;
      }

      const isTransient = this.state.error ? this.isTransientError(this.state.error) : false;
      const errorMessage = this.state.error ? this.getErrorDisplayMessage(this.state.error) : 'Component error';

      return (
        <Alert variant="destructive" className="my-2">
          <AlertCircle className="h-4 w-4" />
          <AlertDescription className="flex items-center justify-between">
            <div className="flex-1">
              <p className="font-medium">{errorMessage}</p>
              {isTransient && this.state.retryCount < 1 && (
                <p className="text-xs mt-1 opacity-75">Retrying automatically...</p>
              )}
            </div>
            
            <div className="flex items-center space-x-2 ml-4">
              {/* Toggle error details button */}
              {(this.props.showErrorDetails || process.env.NODE_ENV === 'development') && (
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={this.toggleDetails}
                  className="h-6 px-2"
                >
                  {this.state.showDetails ? (
                    <EyeOff className="h-3 w-3" />
                  ) : (
                    <Eye className="h-3 w-3" />
                  )}
                </Button>
              )}
              
              {/* Retry button */}
              {(isTransient || this.state.retryCount > 0) && (
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={this.handleRetry}
                  className="h-6 px-2"
                  disabled={this.state.retryCount >= 3}
                >
                  <RefreshCw className="h-3 w-3" />
                </Button>
              )}
            </div>
          </AlertDescription>
          
          {/* Error details */}
          {this.state.showDetails && this.state.error && (
            <div className="mt-3 p-3 bg-red-50 border border-red-200 rounded text-xs">
              <div className="space-y-2">
                <div>
                  <strong>Error:</strong> {this.state.error.message}
                </div>
                {this.state.errorId && (
                  <div>
                    <strong>ID:</strong> {this.state.errorId}
                  </div>
                )}
                {this.props.componentName && (
                  <div>
                    <strong>Component:</strong> {this.props.componentName}
                  </div>
                )}
                <div>
                  <strong>Retries:</strong> {this.state.retryCount}
                </div>
                {process.env.NODE_ENV === 'development' && this.state.error.stack && (
                  <details className="mt-2">
                    <summary className="cursor-pointer font-medium">Stack Trace</summary>
                    <pre className="mt-1 text-xs bg-red-100 p-2 rounded overflow-x-auto">
                      {this.state.error.stack}
                    </pre>
                  </details>
                )}
              </div>
            </div>
          )}
        </Alert>
      );
    }

    return this.props.children;
  }
}

// Higher-order component wrapper for easy use
export function withErrorBoundary<P extends object>(
  WrappedComponent: React.ComponentType<P>,
  errorBoundaryProps?: Omit<Props, 'children'>
) {
  const displayName = WrappedComponent.displayName || WrappedComponent.name || 'Component';
  
  const WithErrorBoundaryComponent = (props: P) => (
    <ComponentErrorBoundary
      componentName={displayName}
      {...errorBoundaryProps}
    >
      <WrappedComponent {...props} />
    </ComponentErrorBoundary>
  );
  
  WithErrorBoundaryComponent.displayName = `withErrorBoundary(${displayName})`;
  
  return WithErrorBoundaryComponent;
}

// Hook for programmatic error boundary control
export function useErrorBoundary() {
  const [error, setError] = React.useState<Error | null>(null);
  
  React.useEffect(() => {
    if (error) {
      throw error;
    }
  }, [error]);
  
  const captureError = React.useCallback((error: Error) => {
    setError(error);
  }, []);
  
  const resetError = React.useCallback(() => {
    setError(null);
  }, []);
  
  return { captureError, resetError };
}