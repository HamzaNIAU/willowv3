/**
 * Enhanced API Client with Smart Retry Logic
 * 
 * Features:
 * - Request deduplication to prevent duplicate API calls
 * - Exponential backoff with jitter
 * - Network-aware retry logic
 * - Optimistic updates with rollback capability
 * - Offline request queueing
 * - Circuit breaker pattern
 * - Request prioritization
 * - Automatic timeout management
 */

import { createClient } from '@/lib/supabase/client';

// Types
interface RequestConfig {
  method: 'GET' | 'POST' | 'PUT' | 'DELETE' | 'PATCH';
  headers?: Record<string, string>;
  body?: any;
  timeout?: number;
  priority?: RequestPriority;
  retryConfig?: RetryConfig;
  cacheKey?: string;
  optimistic?: boolean;
}

interface RetryConfig {
  maxAttempts: number;
  baseDelay: number;
  maxDelay: number;
  exponentialBase: number;
  jitterFactor: number;
  retryCondition?: (error: Error, attempt: number) => boolean;
}

interface CircuitBreakerConfig {
  failureThreshold: number;
  recoveryTimeout: number;
  monitoringWindow: number;
}

interface QueuedRequest {
  id: string;
  url: string;
  config: RequestConfig;
  priority: RequestPriority;
  timestamp: number;
  resolve: (value: any) => void;
  reject: (error: any) => void;
}

enum RequestPriority {
  LOW = 1,
  NORMAL = 2,
  HIGH = 3,
  CRITICAL = 4,
}

enum CircuitState {
  CLOSED = 'closed',
  OPEN = 'open',
  HALF_OPEN = 'half_open',
}

// Default configurations
const DEFAULT_RETRY_CONFIG: RetryConfig = {
  maxAttempts: 3,
  baseDelay: 1000,
  maxDelay: 30000,
  exponentialBase: 2,
  jitterFactor: 0.1,
  retryCondition: (error: Error, attempt: number) => {
    // Retry on network errors, timeouts, and 5xx status codes
    if (error.name === 'NetworkError' || error.name === 'TimeoutError') return true;
    if ('status' in error && typeof error.status === 'number') {
      return error.status >= 500 || error.status === 429; // Server errors and rate limits
    }
    return attempt < 2; // Retry unknown errors once
  },
};

const DEFAULT_CIRCUIT_BREAKER_CONFIG: CircuitBreakerConfig = {
  failureThreshold: 5,
  recoveryTimeout: 30000,
  monitoringWindow: 60000,
};

const API_URL = process.env.NEXT_PUBLIC_BACKEND_URL || '';

// Enhanced API Client Class
export class EnhancedAPIClient {
  private inFlightRequests = new Map<string, Promise<any>>();
  private circuitBreakers = new Map<string, CircuitBreakerState>();
  private requestQueue: QueuedRequest[] = [];
  private isOnline = true;
  private queueProcessor: NodeJS.Timeout | null = null;
  private requestMetrics = new Map<string, RequestMetrics>();
  
  constructor() {
    this.setupNetworkMonitoring();
    this.startQueueProcessor();
  }

  /**
   * Make an API request with enhanced error handling and retry logic
   */
  async request<T = any>(url: string, config: RequestConfig): Promise<T> {
    const requestId = this.generateRequestId(url, config);
    const fullUrl = url.startsWith('http') ? url : `${API_URL}${url}`;
    
    // Check for duplicate in-flight requests
    if (this.inFlightRequests.has(requestId) && !config.optimistic) {
      console.log(`Deduplicating request: ${requestId}`);
      return this.inFlightRequests.get(requestId)!;
    }
    
    // Check circuit breaker
    const endpoint = this.extractEndpoint(fullUrl);
    const circuitBreaker = this.getCircuitBreaker(endpoint);
    if (circuitBreaker.state === CircuitState.OPEN) {
      const error = new Error(`Circuit breaker open for ${endpoint}`);
      error.name = 'CircuitBreakerError';
      throw error;
    }
    
    // Queue request if offline
    if (!this.isOnline) {
      return this.queueRequest(fullUrl, config);
    }
    
    // Create and store the request promise
    const requestPromise = this.executeRequest<T>(fullUrl, config, requestId);
    this.inFlightRequests.set(requestId, requestPromise);
    
    try {
      const result = await requestPromise;
      this.recordSuccess(endpoint);
      return result;
    } catch (error) {
      this.recordFailure(endpoint, error as Error);
      throw error;
    } finally {
      this.inFlightRequests.delete(requestId);
    }
  }

  /**
   * Execute the actual HTTP request with retry logic
   */
  private async executeRequest<T>(
    url: string,
    config: RequestConfig,
    requestId: string
  ): Promise<T> {
    const retryConfig = { ...DEFAULT_RETRY_CONFIG, ...config.retryConfig };
    const startTime = Date.now();
    
    let lastError: Error | null = null;
    
    for (let attempt = 1; attempt <= retryConfig.maxAttempts; attempt++) {
      try {
        console.log(`API Request attempt ${attempt}/${retryConfig.maxAttempts}: ${config.method} ${url}`);
        
        const response = await this.performRequest(url, config);
        
        // Record latency
        const latency = Date.now() - startTime;
        this.recordLatency(this.extractEndpoint(url), latency);
        
        return response;
        
      } catch (error) {
        lastError = error as Error;
        console.warn(`Request attempt ${attempt} failed:`, error);
        
        // Check if we should retry
        if (attempt < retryConfig.maxAttempts && retryConfig.retryCondition!(lastError, attempt)) {
          const delay = this.calculateRetryDelay(attempt, retryConfig);
          console.log(`Retrying in ${delay}ms...`);
          await this.sleep(delay);
          continue;
        }
        
        break;
      }
    }
    
    throw lastError || new Error('Request failed after all retry attempts');
  }

  /**
   * Perform the actual HTTP request
   */
  private async performRequest(url: string, config: RequestConfig): Promise<any> {
    const controller = new AbortController();
    const timeout = config.timeout || 30000;
    
    // Set up timeout
    const timeoutId = setTimeout(() => {
      controller.abort();
    }, timeout);
    
    try {
      // Get authentication token
      const supabase = createClient();
      const { data: { session } } = await supabase.auth.getSession();
      
      // Prepare headers
      const headers: Record<string, string> = {
        'Content-Type': 'application/json',
        ...config.headers,
      };
      
      if (session?.access_token) {
        headers['Authorization'] = `Bearer ${session.access_token}`;
      }
      
      // Prepare fetch options
      const fetchOptions: RequestInit = {
        method: config.method,
        headers,
        signal: controller.signal,
      };
      
      if (config.body && config.method !== 'GET') {
        fetchOptions.body = typeof config.body === 'string' 
          ? config.body 
          : JSON.stringify(config.body);
      }
      
      // Make the request
      const response = await fetch(url, fetchOptions);
      
      if (!response.ok) {
        const error = new Error(`HTTP ${response.status}: ${response.statusText}`);
        (error as any).status = response.status;
        (error as any).response = response;
        throw error;
      }
      
      // Parse response
      const contentType = response.headers.get('content-type');
      if (contentType?.includes('application/json')) {
        return await response.json();
      } else {
        return await response.text();
      }
      
    } catch (error) {
      if (controller.signal.aborted) {
        const timeoutError = new Error('Request timeout');
        timeoutError.name = 'TimeoutError';
        throw timeoutError;
      }
      
      // Network errors
      if (error instanceof TypeError && error.message.includes('fetch')) {
        const networkError = new Error('Network error');
        networkError.name = 'NetworkError';
        throw networkError;
      }
      
      throw error;
    } finally {
      clearTimeout(timeoutId);
    }
  }

  /**
   * Queue request for offline processing
   */
  private async queueRequest<T>(url: string, config: RequestConfig): Promise<T> {
    return new Promise((resolve, reject) => {
      const queuedRequest: QueuedRequest = {
        id: this.generateRequestId(url, config),
        url,
        config,
        priority: config.priority || RequestPriority.NORMAL,
        timestamp: Date.now(),
        resolve,
        reject,
      };
      
      // Insert request in priority order
      const insertIndex = this.requestQueue.findIndex(
        req => req.priority < queuedRequest.priority
      );
      
      if (insertIndex === -1) {
        this.requestQueue.push(queuedRequest);
      } else {
        this.requestQueue.splice(insertIndex, 0, queuedRequest);
      }
      
      console.log(`Queued request (priority ${queuedRequest.priority}): ${url}`);
    });
  }

  /**
   * Process queued requests when back online
   */
  private startQueueProcessor() {
    this.queueProcessor = setInterval(async () => {
      if (!this.isOnline || this.requestQueue.length === 0) return;
      
      const request = this.requestQueue.shift();
      if (!request) return;
      
      try {
        console.log(`Processing queued request: ${request.url}`);
        const result = await this.executeRequest(request.url, request.config, request.id);
        request.resolve(result);
      } catch (error) {
        console.error(`Failed to process queued request: ${request.url}`, error);
        request.reject(error);
      }
    }, 1000);
  }

  /**
   * Setup network monitoring
   */
  private setupNetworkMonitoring() {
    // Listen for online/offline events
    window.addEventListener('online', () => {
      console.log('Network: Back online');
      this.isOnline = true;
    });
    
    window.addEventListener('offline', () => {
      console.log('Network: Gone offline');
      this.isOnline = false;
    });
    
    // Initial state
    this.isOnline = navigator.onLine;
  }

  /**
   * Calculate retry delay with exponential backoff and jitter
   */
  private calculateRetryDelay(attempt: number, config: RetryConfig): number {
    const exponentialDelay = config.baseDelay * Math.pow(config.exponentialBase, attempt - 1);
    const jitter = exponentialDelay * config.jitterFactor * (Math.random() * 2 - 1);
    const totalDelay = Math.min(exponentialDelay + jitter, config.maxDelay);
    return Math.max(totalDelay, 0);
  }

  /**
   * Generate unique request ID for deduplication
   */
  private generateRequestId(url: string, config: RequestConfig): string {
    const key = config.cacheKey || `${config.method}:${url}:${JSON.stringify(config.body || {})}`;
    return btoa(key).replace(/[^a-zA-Z0-9]/g, '');
  }

  /**
   * Extract endpoint name from URL for circuit breaker
   */
  private extractEndpoint(url: string): string {
    try {
      const urlObj = new URL(url);
      const pathParts = urlObj.pathname.split('/').filter(Boolean);
      return pathParts.slice(0, 2).join('/'); // e.g., "api/agents"
    } catch {
      return url;
    }
  }

  /**
   * Get or create circuit breaker for endpoint
   */
  private getCircuitBreaker(endpoint: string): CircuitBreakerState {
    if (!this.circuitBreakers.has(endpoint)) {
      this.circuitBreakers.set(endpoint, {
        state: CircuitState.CLOSED,
        failureCount: 0,
        lastFailureTime: 0,
        successCount: 0,
      });
    }
    return this.circuitBreakers.get(endpoint)!;
  }

  /**
   * Record successful request
   */
  private recordSuccess(endpoint: string) {
    const circuitBreaker = this.getCircuitBreaker(endpoint);
    circuitBreaker.successCount++;
    
    if (circuitBreaker.state === CircuitState.HALF_OPEN) {
      if (circuitBreaker.successCount >= 3) {
        circuitBreaker.state = CircuitState.CLOSED;
        circuitBreaker.failureCount = 0;
        console.log(`Circuit breaker closed for ${endpoint}`);
      }
    }
  }

  /**
   * Record failed request
   */
  private recordFailure(endpoint: string, error: Error) {
    const circuitBreaker = this.getCircuitBreaker(endpoint);
    circuitBreaker.failureCount++;
    circuitBreaker.lastFailureTime = Date.now();
    
    if (circuitBreaker.state === CircuitState.CLOSED) {
      if (circuitBreaker.failureCount >= DEFAULT_CIRCUIT_BREAKER_CONFIG.failureThreshold) {
        circuitBreaker.state = CircuitState.OPEN;
        console.warn(`Circuit breaker opened for ${endpoint}`);
        
        // Schedule recovery attempt
        setTimeout(() => {
          if (circuitBreaker.state === CircuitState.OPEN) {
            circuitBreaker.state = CircuitState.HALF_OPEN;
            circuitBreaker.successCount = 0;
            console.log(`Circuit breaker half-open for ${endpoint}`);
          }
        }, DEFAULT_CIRCUIT_BREAKER_CONFIG.recoveryTimeout);
      }
    }
  }

  /**
   * Record request latency
   */
  private recordLatency(endpoint: string, latency: number) {
    if (!this.requestMetrics.has(endpoint)) {
      this.requestMetrics.set(endpoint, {
        averageLatency: latency,
        requestCount: 1,
      });
    } else {
      const metrics = this.requestMetrics.get(endpoint)!;
      metrics.averageLatency = (metrics.averageLatency * metrics.requestCount + latency) / (metrics.requestCount + 1);
      metrics.requestCount++;
    }
  }

  /**
   * Utility function to sleep
   */
  private sleep(ms: number): Promise<void> {
    return new Promise(resolve => setTimeout(resolve, ms));
  }

  /**
   * Get current metrics
   */
  getMetrics() {
    return {
      circuitBreakers: Object.fromEntries(this.circuitBreakers),
      requestMetrics: Object.fromEntries(this.requestMetrics),
      queueLength: this.requestQueue.length,
      isOnline: this.isOnline,
      inFlightRequests: this.inFlightRequests.size,
    };
  }

  /**
   * Reset all metrics and circuit breakers
   */
  reset() {
    this.circuitBreakers.clear();
    this.requestMetrics.clear();
    this.inFlightRequests.clear();
    this.requestQueue.length = 0;
  }

  /**
   * Cleanup
   */
  destroy() {
    if (this.queueProcessor) {
      clearInterval(this.queueProcessor);
    }
    this.reset();
  }
}

// Supporting interfaces
interface CircuitBreakerState {
  state: CircuitState;
  failureCount: number;
  lastFailureTime: number;
  successCount: number;
}

interface RequestMetrics {
  averageLatency: number;
  requestCount: number;
}

// Singleton instance
const apiClient = new EnhancedAPIClient();

// Enhanced API functions that use the smart client
export const enhancedApiClient = {
  get: <T = any>(url: string, config?: Partial<RequestConfig>) => 
    apiClient.request<T>(url, { method: 'GET', ...config }),
    
  post: <T = any>(url: string, data?: any, config?: Partial<RequestConfig>) => 
    apiClient.request<T>(url, { method: 'POST', body: data, ...config }),
    
  put: <T = any>(url: string, data?: any, config?: Partial<RequestConfig>) => 
    apiClient.request<T>(url, { method: 'PUT', body: data, ...config }),
    
  delete: <T = any>(url: string, config?: Partial<RequestConfig>) => 
    apiClient.request<T>(url, { method: 'DELETE', ...config }),
    
  patch: <T = any>(url: string, data?: any, config?: Partial<RequestConfig>) => 
    apiClient.request<T>(url, { method: 'PATCH', body: data, ...config }),
};

// Export types and enums
export { RequestPriority, type RequestConfig, type RetryConfig };

// Export for monitoring and debugging
export const getApiClientMetrics = () => apiClient.getMetrics();
export const resetApiClient = () => apiClient.reset();