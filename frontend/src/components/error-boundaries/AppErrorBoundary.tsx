'use client';

import React, { Component, ReactNode } from 'react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { AlertTriangle, RefreshCw, Home, Bug } from 'lucide-react';

interface Props {
  children: ReactNode;
  fallback?: ReactNode;
  onError?: (error: Error, errorInfo: React.ErrorInfo) => void;
}

interface State {
  hasError: boolean;
  error: Error | null;
  errorInfo: React.ErrorInfo | null;
  errorId: string | null;
  retryCount: number;
}

/**
 * Top-level error boundary for the entire application
 * Handles critical errors and provides recovery options
 */
export class AppErrorBoundary extends Component<Props, State> {
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
    // Generate unique error ID for tracking
    const errorId = `app-error-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;
    
    return {
      hasError: true,
      error,
      errorId,
    };
  }

  componentDidCatch(error: Error, errorInfo: React.ErrorInfo) {
    console.error('App Error Boundary caught an error:', error, errorInfo);
    
    this.setState({
      errorInfo,
    });

    // Report error to monitoring service
    this.reportError(error, errorInfo);
    
    // Call custom error handler
    this.props.onError?.(error, errorInfo);
    
    // Auto-retry for certain error types
    this.scheduleAutoRetry(error);
  }

  componentWillUnmount() {
    // Clean up any pending retry timeouts
    this.retryTimeouts.forEach(clearTimeout);
  }

  private reportError = (error: Error, errorInfo: React.ErrorInfo) => {
    try {
      // Report to Sentry, PostHog, or other monitoring service
      if (typeof window !== 'undefined') {
        // Example with PostHog
        if ((window as any).posthog) {
          (window as any).posthog.capture('app_error_boundary_triggered', {
            error_message: error.message,
            error_stack: error.stack,
            component_stack: errorInfo.componentStack,
            error_id: this.state.errorId,
            retry_count: this.state.retryCount,
            user_agent: navigator.userAgent,
            url: window.location.href,
          });
        }
        
        // Example with Sentry
        if ((window as any).Sentry) {
          (window as any).Sentry.withScope((scope: any) => {
            scope.setTag('error_boundary', 'app');
            scope.setContext('errorInfo', errorInfo);
            scope.setContext('errorId', this.state.errorId);
            (window as any).Sentry.captureException(error);
          });
        }
      }
    } catch (reportingError) {
      console.error('Failed to report error:', reportingError);
    }
  };

  private scheduleAutoRetry = (error: Error) => {
    // Only auto-retry for certain recoverable errors
    const isRecoverable = this.isRecoverableError(error);
    
    if (isRecoverable && this.state.retryCount < 2) {
      const retryDelay = Math.min(1000 * Math.pow(2, this.state.retryCount), 5000);
      
      console.log(`Scheduling auto-retry in ${retryDelay}ms (attempt ${this.state.retryCount + 1})`);
      
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
    ];
    
    return recoverablePatterns.some(pattern => 
      pattern.test(error.message) || pattern.test(error.name)
    );
  };

  private handleRetry = () => {
    console.log('Attempting to recover from error...');
    
    this.setState(prevState => ({
      hasError: false,
      error: null,
      errorInfo: null,
      retryCount: prevState.retryCount + 1,
    }));
  };

  private handleManualRetry = () => {
    this.handleRetry();
  };

  private handleReload = () => {
    window.location.reload();
  };

  private handleGoHome = () => {
    window.location.href = '/';
  };

  private handleReportBug = () => {
    const errorDetails = {
      message: this.state.error?.message,
      stack: this.state.error?.stack,
      errorId: this.state.errorId,
      userAgent: navigator.userAgent,
      url: window.location.href,
      timestamp: new Date().toISOString(),
    };
    
    const subject = `Bug Report: ${this.state.error?.message || 'Unknown Error'}`;
    const body = `Please describe what you were doing when this error occurred:\n\n\n\nError Details:\n${JSON.stringify(errorDetails, null, 2)}`;
    
    const mailtoUrl = `mailto:support@example.com?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`;
    window.open(mailtoUrl);
  };

  render() {
    if (this.state.hasError) {
      // Use custom fallback if provided
      if (this.props.fallback) {
        return this.props.fallback;
      }

      const isRecoverable = this.state.error ? this.isRecoverableError(this.state.error) : false;

      return (
        <div className="min-h-screen bg-gray-50 flex items-center justify-center p-4">
          <Card className="w-full max-w-2xl">
            <CardHeader className="text-center">
              <div className="mx-auto w-16 h-16 bg-red-100 rounded-full flex items-center justify-center mb-4">
                <AlertTriangle className="w-8 h-8 text-red-600" />
              </div>
              <CardTitle className="text-2xl text-gray-900">
                Oops! Something went wrong
              </CardTitle>
              <p className="text-gray-600 mt-2">
                We encountered an unexpected error. Don't worry, we're here to help you get back on track.
              </p>
            </CardHeader>
            
            <CardContent className="space-y-6">
              {/* Error ID for support */}
              {this.state.errorId && (
                <div className="bg-gray-100 p-3 rounded-lg">
                  <p className="text-sm text-gray-600">
                    <strong>Error ID:</strong> {this.state.errorId}
                  </p>
                  <p className="text-xs text-gray-500 mt-1">
                    Include this ID when reporting the issue for faster support.
                  </p>
                </div>
              )}

              {/* Error details (in development) */}
              {process.env.NODE_ENV === 'development' && this.state.error && (
                <details className="bg-red-50 p-4 rounded-lg border border-red-200">
                  <summary className="text-red-800 font-medium cursor-pointer">
                    Error Details (Development)
                  </summary>
                  <div className="mt-3 space-y-2">
                    <p className="text-sm text-red-700">
                      <strong>Message:</strong> {this.state.error.message}
                    </p>
                    {this.state.error.stack && (
                      <pre className="text-xs text-red-600 bg-red-100 p-2 rounded overflow-x-auto">
                        {this.state.error.stack}
                      </pre>
                    )}
                  </div>
                </details>
              )}

              {/* Recovery actions */}
              <div className="space-y-3">
                <h3 className="font-medium text-gray-900">What would you like to do?</h3>
                
                <div className="grid gap-3 sm:grid-cols-2">
                  {isRecoverable && this.state.retryCount < 3 && (
                    <Button
                      onClick={this.handleManualRetry}
                      variant="default"
                      className="w-full"
                    >
                      <RefreshCw className="w-4 h-4 mr-2" />
                      Try Again
                    </Button>
                  )}
                  
                  <Button
                    onClick={this.handleGoHome}
                    variant="outline"
                    className="w-full"
                  >
                    <Home className="w-4 h-4 mr-2" />
                    Go to Home
                  </Button>
                  
                  <Button
                    onClick={this.handleReload}
                    variant="outline"
                    className="w-full"
                  >
                    <RefreshCw className="w-4 h-4 mr-2" />
                    Reload Page
                  </Button>
                  
                  <Button
                    onClick={this.handleReportBug}
                    variant="outline"
                    className="w-full"
                  >
                    <Bug className="w-4 h-4 mr-2" />
                    Report Bug
                  </Button>
                </div>
              </div>

              {/* Retry count indicator */}
              {this.state.retryCount > 0 && (
                <div className="text-center text-sm text-gray-500">
                  Retry attempts: {this.state.retryCount}
                </div>
              )}

              {/* Help text */}
              <div className="text-center text-sm text-gray-500 border-t pt-4">
                If this problem persists, please contact our support team with the error ID above.
              </div>
            </CardContent>
          </Card>
        </div>
      );
    }

    return this.props.children;
  }
}