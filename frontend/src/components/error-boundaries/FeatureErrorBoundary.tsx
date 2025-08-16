'use client';

import React, { Component, ReactNode } from 'react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { AlertCircle, RefreshCw, ArrowLeft } from 'lucide-react';

interface Props {
  children: ReactNode;
  featureName: string;
  fallback?: ReactNode;
  onError?: (error: Error, errorInfo: React.ErrorInfo) => void;
  onRetry?: () => void;
  onNavigateBack?: () => void;
}

interface State {
  hasError: boolean;
  error: Error | null;
  errorInfo: React.ErrorInfo | null;
  errorId: string | null;
  retryCount: number;
}

/**
 * Feature-level error boundary for specific application features
 * Provides more targeted error handling and recovery options
 */
export class FeatureErrorBoundary extends Component<Props, State> {
  private retryTimeouts: NodeJS.Timeout[] = [];

  constructor(props: Props) {
    super(props);
    this.state = {
      hasError: false,
      error: null,
      errorInfo: null,
      errorId: null,
      retryCount: 0,
    };
  }

  static getDerivedStateFromError(error: Error): Partial<State> {
    const errorId = `feature-error-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;
    
    return {
      hasError: true,
      error,
      errorId,
    };
  }

  componentDidCatch(error: Error, errorInfo: React.ErrorInfo) {
    console.error(`Feature Error Boundary (${this.props.featureName}) caught an error:`, error, errorInfo);
    
    this.setState({
      errorInfo,
    });

    // Report error with feature context
    this.reportError(error, errorInfo);
    
    // Call custom error handler
    this.props.onError?.(error, errorInfo);
    
    // Auto-retry for recoverable errors
    this.scheduleAutoRetry(error);
  }

  componentWillUnmount() {
    this.retryTimeouts.forEach(clearTimeout);
  }

  private reportError = (error: Error, errorInfo: React.ErrorInfo) => {
    try {
      if (typeof window !== 'undefined') {
        // Report to monitoring with feature context
        if ((window as any).posthog) {
          (window as any).posthog.capture('feature_error_boundary_triggered', {
            feature_name: this.props.featureName,
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
            scope.setTag('error_boundary', 'feature');
            scope.setTag('feature_name', this.props.featureName);
            scope.setContext('errorInfo', errorInfo);
            scope.setContext('errorId', this.state.errorId);
            (window as any).Sentry.captureException(error);
          });
        }
      }
    } catch (reportingError) {
      console.error('Failed to report feature error:', reportingError);
    }
  };

  private scheduleAutoRetry = (error: Error) => {
    const isRecoverable = this.isRecoverableError(error);
    
    if (isRecoverable && this.state.retryCount < 2) {
      const retryDelay = Math.min(500 * Math.pow(2, this.state.retryCount), 3000);
      
      const timeout = setTimeout(() => {
        this.handleRetry();
      }, retryDelay);
      
      this.retryTimeouts.push(timeout);
    }
  };

  private isRecoverableError = (error: Error): boolean => {
    const recoverablePatterns = [
      /network/i,
      /fetch/i,
      /loading/i,
      /timeout/i,
      /suspended/i,
      /chunk/i, // Chunk loading errors
      /dynamic import/i,
    ];
    
    return recoverablePatterns.some(pattern => 
      pattern.test(error.message) || pattern.test(error.name)
    );
  };

  private handleRetry = () => {
    console.log(`Attempting to recover ${this.props.featureName} feature...`);
    
    this.setState(prevState => ({
      hasError: false,
      error: null,
      errorInfo: null,
      retryCount: prevState.retryCount + 1,
    }));
    
    // Call custom retry handler
    this.props.onRetry?.();
  };

  private handleNavigateBack = () => {
    if (this.props.onNavigateBack) {
      this.props.onNavigateBack();
    } else {
      // Default navigation back
      if (typeof window !== 'undefined' && window.history.length > 1) {
        window.history.back();
      } else {
        window.location.href = '/';
      }
    }
  };

  private getErrorSeverity = (error: Error): 'low' | 'medium' | 'high' => {
    if (this.isRecoverableError(error)) return 'low';
    
    const highSeverityPatterns = [
      /security/i,
      /unauthorized/i,
      /forbidden/i,
      /billing/i,
    ];
    
    if (highSeverityPatterns.some(pattern => pattern.test(error.message))) {
      return 'high';
    }
    
    return 'medium';
  };

  private getErrorMessage = (error: Error): string => {
    const featureName = this.props.featureName.toLowerCase();
    const severity = this.getErrorSeverity(error);
    
    if (severity === 'high') {
      return `We're having trouble accessing the ${featureName} feature due to a security or billing issue.`;
    }
    
    if (this.isRecoverableError(error)) {
      return `The ${featureName} feature is temporarily unavailable. We're trying to fix this automatically.`;
    }
    
    return `Something went wrong with the ${featureName} feature.`;
  };

  render() {
    if (this.state.hasError) {
      // Use custom fallback if provided
      if (this.props.fallback) {
        return this.props.fallback;
      }

      const isRecoverable = this.state.error ? this.isRecoverableError(this.state.error) : false;
      const errorMessage = this.state.error ? this.getErrorMessage(this.state.error) : 'Something went wrong';
      const severity = this.state.error ? this.getErrorSeverity(this.state.error) : 'medium';

      return (
        <div className="flex items-center justify-center p-8">
          <Card className="w-full max-w-lg">
            <CardHeader className="text-center">
              <div className={`mx-auto w-12 h-12 rounded-full flex items-center justify-center mb-3 ${
                severity === 'high' ? 'bg-red-100' : 
                severity === 'medium' ? 'bg-orange-100' : 'bg-yellow-100'
              }`}>
                <AlertCircle className={`w-6 h-6 ${
                  severity === 'high' ? 'text-red-600' : 
                  severity === 'medium' ? 'text-orange-600' : 'text-yellow-600'
                }`} />
              </div>
              <CardTitle className="text-lg text-gray-900">
                {this.props.featureName} Unavailable
              </CardTitle>
              <p className="text-gray-600 text-sm mt-2">
                {errorMessage}
              </p>
            </CardHeader>
            
            <CardContent className="space-y-4">
              {/* Error ID for debugging */}
              {process.env.NODE_ENV === 'development' && this.state.errorId && (
                <div className="bg-gray-50 p-2 rounded text-xs text-gray-500">
                  Error ID: {this.state.errorId}
                </div>
              )}

              {/* Error details in development */}
              {process.env.NODE_ENV === 'development' && this.state.error && (
                <details className="bg-gray-50 p-3 rounded text-xs">
                  <summary className="cursor-pointer text-gray-700 font-medium">
                    Debug Info
                  </summary>
                  <div className="mt-2 space-y-1">
                    <p><strong>Error:</strong> {this.state.error.message}</p>
                    <p><strong>Feature:</strong> {this.props.featureName}</p>
                    <p><strong>Retries:</strong> {this.state.retryCount}</p>
                  </div>
                </details>
              )}

              {/* Recovery actions */}
              <div className="space-y-2">
                {isRecoverable && this.state.retryCount < 3 && (
                  <Button
                    onClick={this.handleRetry}
                    variant="default"
                    size="sm"
                    className="w-full"
                  >
                    <RefreshCw className="w-4 h-4 mr-2" />
                    Try Again
                  </Button>
                )}
                
                <Button
                  onClick={this.handleNavigateBack}
                  variant="outline"
                  size="sm"
                  className="w-full"
                >
                  <ArrowLeft className="w-4 h-4 mr-2" />
                  Go Back
                </Button>
              </div>

              {/* Auto-retry indicator */}
              {isRecoverable && this.state.retryCount < 2 && (
                <div className="text-center">
                  <div className="inline-flex items-center text-xs text-gray-500">
                    <div className="animate-spin rounded-full h-3 w-3 border-b-2 border-gray-400 mr-2"></div>
                    Automatically retrying...
                  </div>
                </div>
              )}

              {/* Retry count */}
              {this.state.retryCount > 0 && (
                <div className="text-center text-xs text-gray-500">
                  Attempted {this.state.retryCount} time{this.state.retryCount !== 1 ? 's' : ''}
                </div>
              )}
            </CardContent>
          </Card>
        </div>
      );
    }

    return this.props.children;
  }
}

// Convenience wrapper for common features
export const AgentErrorBoundary = ({ children, ...props }: Omit<Props, 'featureName'>) => (
  <FeatureErrorBoundary featureName="Agent" {...props}>
    {children}
  </FeatureErrorBoundary>
);

export const ThreadErrorBoundary = ({ children, ...props }: Omit<Props, 'featureName'>) => (
  <FeatureErrorBoundary featureName="Thread" {...props}>
    {children}
  </FeatureErrorBoundary>
);

export const BillingErrorBoundary = ({ children, ...props }: Omit<Props, 'featureName'>) => (
  <FeatureErrorBoundary featureName="Billing" {...props}>
    {children}
  </FeatureErrorBoundary>
);

export const WorkflowErrorBoundary = ({ children, ...props }: Omit<Props, 'featureName'>) => (
  <FeatureErrorBoundary featureName="Workflow" {...props}>
    {children}
  </FeatureErrorBoundary>
);