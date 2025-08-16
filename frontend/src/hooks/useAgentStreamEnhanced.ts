import { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import { toast } from 'sonner';
import {
  streamAgent,
  getAgentStatus,
  stopAgent,
  AgentRun,
  getMessages,
} from '@/lib/api';
import {
  UnifiedMessage,
  ParsedContent,
  ParsedMetadata,
} from '@/components/thread/types';
import { safeJsonParse } from '@/components/thread/utils';

// Types for enhanced stream monitoring
interface ConnectionHealth {
  status: 'healthy' | 'degraded' | 'disconnected';
  lastHeartbeat: number;
  latency: number;
  reconnectAttempts: number;
}

interface ProgressInfo {
  percentage: number;
  currentStep: string;
  estimatedTimeRemaining?: number;
  completedSteps: string[];
}

interface ErrorEvent {
  timestamp: number;
  type: string;
  message: string;
  severity: 'low' | 'medium' | 'high' | 'critical';
  recoverable: boolean;
}

interface EnhancedStreamState {
  connectionHealth: ConnectionHealth;
  progress: ProgressInfo;
  retryCount: number;
  errorHistory: ErrorEvent[];
  isRecovering: boolean;
  queuePosition?: number;
}

interface StatusUpdate {
  status: string;
  message: string;
  progress?: number;
  step?: string;
  queue_position?: number;
  estimated_completion?: string;
}

// Enhanced callbacks interface
export interface EnhancedAgentStreamCallbacks {
  onMessage: (message: UnifiedMessage) => void;
  onStatusChange?: (status: string, details?: StatusUpdate) => void;
  onProgressUpdate?: (progress: ProgressInfo) => void;
  onConnectionChange?: (health: ConnectionHealth) => void;
  onError?: (error: ErrorEvent) => void;
  onRecovery?: (successful: boolean) => void;
  onClose?: (finalStatus: string) => void;
  onAssistantStart?: () => void;
  onAssistantChunk?: (chunk: { content: string }) => void;
}

// Enhanced hook result interface
export interface UseAgentStreamEnhancedResult {
  // Basic state
  status: string;
  textContent: string;
  toolCall: ParsedContent | null;
  error: string | null;
  agentRunId: string | null;
  
  // Enhanced state
  streamState: EnhancedStreamState;
  
  // Actions
  startStreaming: (runId: string) => void;
  stopStreaming: () => Promise<void>;
  retryConnection: () => Promise<void>;
  clearErrors: () => void;
}

const HEARTBEAT_INTERVAL = 5000; // 5 seconds
const STATUS_POLL_INTERVAL = 5000; // 5 seconds
const MAX_RECONNECT_ATTEMPTS = 5;
const RECONNECT_DELAYS = [1000, 2000, 4000, 8000, 16000]; // Exponential backoff

// Helper function to calculate retry delay with jitter
const calculateRetryDelay = (attempt: number): number => {
  const baseDelay = RECONNECT_DELAYS[Math.min(attempt, RECONNECT_DELAYS.length - 1)];
  const jitter = Math.random() * 0.3 * baseDelay; // 30% jitter
  return baseDelay + jitter;
};

// Helper function to classify errors
const classifyError = (error: string): { type: string; severity: 'low' | 'medium' | 'high' | 'critical'; recoverable: boolean } => {
  const errorLower = error.toLowerCase();
  
  if (errorLower.includes('network') || errorLower.includes('connection')) {
    return { type: 'network', severity: 'medium', recoverable: true };
  }
  if (errorLower.includes('timeout')) {
    return { type: 'timeout', severity: 'medium', recoverable: true };
  }
  if (errorLower.includes('rate limit')) {
    return { type: 'rate_limit', severity: 'high', recoverable: true };
  }
  if (errorLower.includes('billing') || errorLower.includes('quota')) {
    return { type: 'billing', severity: 'critical', recoverable: false };
  }
  if (errorLower.includes('authentication')) {
    return { type: 'auth', severity: 'critical', recoverable: false };
  }
  
  return { type: 'unknown', severity: 'medium', recoverable: true };
};

// Helper function to extract progress from status messages
const extractProgress = (status: string, message: string): Partial<ProgressInfo> => {
  const progress: Partial<ProgressInfo> = {};
  
  // Extract percentage from message
  const percentMatch = message.match(/(\d+)%/);
  if (percentMatch) {
    progress.percentage = parseInt(percentMatch[1]);
  }
  
  // Map status to percentage and step
  switch (status) {
    case 'queued':
      progress.percentage = 0;
      progress.currentStep = 'Queued for execution';
      break;
    case 'initializing':
      progress.percentage = 10;
      progress.currentStep = 'Initializing agent';
      break;
    case 'loading_agent':
      progress.percentage = 20;
      progress.currentStep = 'Loading agent configuration';
      break;
    case 'loading_tools':
      progress.percentage = 30;
      progress.currentStep = 'Loading tools and capabilities';
      break;
    case 'executing':
      progress.percentage = progress.percentage || 50;
      progress.currentStep = 'Processing your request';
      break;
    case 'tool_running':
      progress.percentage = progress.percentage || 70;
      progress.currentStep = 'Running tools';
      break;
    case 'completed':
      progress.percentage = 100;
      progress.currentStep = 'Completed successfully';
      break;
    case 'failed':
      progress.percentage = 0;
      progress.currentStep = 'Execution failed';
      break;
  }
  
  return progress;
};

export function useAgentStreamEnhanced(
  callbacks: EnhancedAgentStreamCallbacks,
  threadId: string,
  setMessages: (messages: UnifiedMessage[]) => void,
): UseAgentStreamEnhancedResult {
  // Basic state
  const [agentRunId, setAgentRunId] = useState<string | null>(null);
  const [status, setStatus] = useState<string>('idle');
  const [textContent, setTextContent] = useState<{ content: string; sequence?: number }[]>([]);
  const [toolCall, setToolCall] = useState<ParsedContent | null>(null);
  const [error, setError] = useState<string | null>(null);
  
  // Enhanced state
  const [streamState, setStreamState] = useState<EnhancedStreamState>({
    connectionHealth: {
      status: 'healthy',
      lastHeartbeat: Date.now(),
      latency: 0,
      reconnectAttempts: 0,
    },
    progress: {
      percentage: 0,
      currentStep: 'Idle',
      completedSteps: [],
    },
    retryCount: 0,
    errorHistory: [],
    isRecovering: false,
  });
  
  // Refs for state management
  const streamCleanupRef = useRef<(() => void) | null>(null);
  const isMountedRef = useRef<boolean>(true);
  const currentRunIdRef = useRef<string | null>(null);
  const threadIdRef = useRef(threadId);
  const setMessagesRef = useRef(setMessages);
  const heartbeatIntervalRef = useRef<NodeJS.Timeout | null>(null);
  const statusPollIntervalRef = useRef<NodeJS.Timeout | null>(null);
  const reconnectTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  
  // Update refs when props change
  useEffect(() => {
    threadIdRef.current = threadId;
  }, [threadId]);
  
  useEffect(() => {
    setMessagesRef.current = setMessages;
  }, [setMessages]);
  
  useEffect(() => {
    return () => {
      isMountedRef.current = false;
      if (heartbeatIntervalRef.current) {
        clearInterval(heartbeatIntervalRef.current);
      }
      if (statusPollIntervalRef.current) {
        clearInterval(statusPollIntervalRef.current);
      }
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
      }
    };
  }, []);
  
  // Computed ordered text content
  const orderedTextContent = useMemo(() => {
    return textContent
      .sort((a, b) => (a.sequence ?? 0) - (b.sequence ?? 0))
      .reduce((acc, curr) => acc + curr.content, '');
  }, [textContent]);
  
  // Update connection health
  const updateConnectionHealth = useCallback((updates: Partial<ConnectionHealth>) => {
    if (!isMountedRef.current) return;
    
    setStreamState(prev => {
      const newHealth = { ...prev.connectionHealth, ...updates };
      
      // Notify callback if status changed
      if (newHealth.status !== prev.connectionHealth.status) {
        callbacks.onConnectionChange?.(newHealth);
      }
      
      return {
        ...prev,
        connectionHealth: newHealth,
      };
    });
  }, [callbacks]);
  
  // Update progress
  const updateProgress = useCallback((updates: Partial<ProgressInfo>) => {
    if (!isMountedRef.current) return;
    
    setStreamState(prev => {
      const newProgress = { ...prev.progress, ...updates };
      
      // Add completed step if moving to next step
      if (updates.currentStep && updates.currentStep !== prev.progress.currentStep) {
        if (prev.progress.currentStep && !newProgress.completedSteps.includes(prev.progress.currentStep)) {
          newProgress.completedSteps = [...newProgress.completedSteps, prev.progress.currentStep];
        }
      }
      
      callbacks.onProgressUpdate?.(newProgress);
      
      return {
        ...prev,
        progress: newProgress,
      };
    });
  }, [callbacks]);
  
  // Add error to history
  const addError = useCallback((errorMessage: string) => {
    if (!isMountedRef.current) return;
    
    const errorInfo = classifyError(errorMessage);
    const errorEvent: ErrorEvent = {
      timestamp: Date.now(),
      message: errorMessage,
      ...errorInfo,
    };
    
    setStreamState(prev => ({
      ...prev,
      errorHistory: [...prev.errorHistory.slice(-9), errorEvent], // Keep last 10 errors
    }));
    
    callbacks.onError?.(errorEvent);
    
    // Show toast for critical errors
    if (errorInfo.severity === 'critical') {
      toast.error(`Critical Error: ${errorMessage}`, { duration: 10000 });
    } else if (errorInfo.severity === 'high') {
      toast.error(`Error: ${errorMessage}`, { duration: 5000 });
    }
  }, [callbacks]);
  
  // Start heartbeat monitoring
  const startHeartbeat = useCallback(() => {
    if (heartbeatIntervalRef.current) {
      clearInterval(heartbeatIntervalRef.current);
    }
    
    heartbeatIntervalRef.current = setInterval(() => {
      const now = Date.now();
      setStreamState(prev => {
        const timeSinceLastHeartbeat = now - prev.connectionHealth.lastHeartbeat;
        
        let newStatus = prev.connectionHealth.status;
        if (timeSinceLastHeartbeat > HEARTBEAT_INTERVAL * 2) {
          newStatus = 'degraded';
        }
        if (timeSinceLastHeartbeat > HEARTBEAT_INTERVAL * 4) {
          newStatus = 'disconnected';
        }
        
        const newHealth = {
          ...prev.connectionHealth,
          status: newStatus,
        };
        
        // Trigger reconnect if disconnected
        if (newStatus === 'disconnected' && !prev.isRecovering && currentRunIdRef.current) {
          retryConnection();
        }
        
        return {
          ...prev,
          connectionHealth: newHealth,
        };
      });
    }, HEARTBEAT_INTERVAL);
  }, []);
  
  // Start status polling
  const startStatusPolling = useCallback(() => {
    if (!currentRunIdRef.current) return;
    
    if (statusPollIntervalRef.current) {
      clearInterval(statusPollIntervalRef.current);
    }
    
    statusPollIntervalRef.current = setInterval(async () => {
      if (!currentRunIdRef.current || !isMountedRef.current) return;
      
      try {
        const statusInfo = await getAgentStatus(currentRunIdRef.current);
        
        // Update heartbeat
        updateConnectionHealth({
          lastHeartbeat: Date.now(),
          status: 'healthy',
        });
        
        // Update progress if status provides information
        if (statusInfo.status) {
          const progressUpdates = extractProgress(statusInfo.status, statusInfo.message || '');
          if (Object.keys(progressUpdates).length > 0) {
            updateProgress(progressUpdates);
          }
          
          // Update queue position if available
          if (statusInfo.queue_position !== undefined) {
            setStreamState(prev => ({
              ...prev,
              queuePosition: statusInfo.queue_position,
            }));
          }
          
          callbacks.onStatusChange?.(statusInfo.status, statusInfo);
        }
        
      } catch (error) {
        console.warn('Status polling failed:', error);
        updateConnectionHealth({
          status: 'degraded',
        });
      }
    }, STATUS_POLL_INTERVAL);
  }, [updateConnectionHealth, updateProgress, callbacks]);
  
  // Retry connection with exponential backoff
  const retryConnection = useCallback(async () => {
    if (!currentRunIdRef.current || !isMountedRef.current) return;
    
    setStreamState(prev => {
      if (prev.isRecovering || prev.connectionHealth.reconnectAttempts >= MAX_RECONNECT_ATTEMPTS) {
        return prev;
      }
      
      return {
        ...prev,
        isRecovering: true,
        connectionHealth: {
          ...prev.connectionHealth,
          reconnectAttempts: prev.connectionHealth.reconnectAttempts + 1,
        },
      };
    });
    
    const currentAttempt = streamState.connectionHealth.reconnectAttempts;
    const delay = calculateRetryDelay(currentAttempt);
    
    console.log(`Attempting to reconnect (attempt ${currentAttempt + 1}/${MAX_RECONNECT_ATTEMPTS}) in ${delay}ms`);
    
    reconnectTimeoutRef.current = setTimeout(async () => {
      if (!isMountedRef.current || !currentRunIdRef.current) return;
      
      try {
        // Try to restart the stream
        startStreaming(currentRunIdRef.current);
        
        // Reset reconnect attempts on success
        setStreamState(prev => ({
          ...prev,
          isRecovering: false,
          connectionHealth: {
            ...prev.connectionHealth,
            reconnectAttempts: 0,
            status: 'healthy',
            lastHeartbeat: Date.now(),
          },
        }));
        
        callbacks.onRecovery?.(true);
        toast.success('Connection restored');
        
      } catch (error) {
        console.error('Reconnection attempt failed:', error);
        
        setStreamState(prev => ({
          ...prev,
          isRecovering: false,
        }));
        
        // If we've exhausted all attempts, mark as failed
        if (currentAttempt >= MAX_RECONNECT_ATTEMPTS - 1) {
          callbacks.onRecovery?.(false);
          addError('Connection failed after maximum retry attempts');
        }
      }
    }, delay);
  }, [streamState.connectionHealth.reconnectAttempts, callbacks, addError]);
  
  // Handle stream messages (similar to original but with enhanced error handling)
  const handleStreamMessage = useCallback((rawData: string) => {
    if (!isMountedRef.current) return;
    
    // Update heartbeat
    updateConnectionHealth({
      lastHeartbeat: Date.now(),
      status: 'healthy',
    });
    
    let processedData = rawData;
    if (processedData.startsWith('data: ')) {
      processedData = processedData.substring(6).trim();
    }
    if (!processedData) return;
    
    // Handle completion messages
    if (processedData.includes('completed') || processedData.includes('Stream ended')) {
      updateProgress({ percentage: 100, currentStep: 'Completed' });
      return;
    }
    
    // Parse JSON message
    const message = safeJsonParse(processedData, null) as UnifiedMessage | null;
    if (!message) {
      console.warn('Failed to parse streamed message:', processedData);
      return;
    }
    
    // Handle error messages
    if (message.type === 'error' || (message as any).status === 'error') {
      const errorMessage = message.content || 'Unknown error occurred';
      addError(errorMessage);
      setError(errorMessage);
      return;
    }
    
    const parsedContent = safeJsonParse<ParsedContent>(message.content, {});
    const parsedMetadata = safeJsonParse<ParsedMetadata>(message.metadata, {});
    
    // Update status
    if (status !== 'streaming') {
      setStatus('streaming');
      updateProgress({ currentStep: 'Processing response' });
    }
    
    // Handle different message types
    switch (message.type) {
      case 'assistant':
        if (parsedMetadata.stream_status === 'chunk' && parsedContent.content) {
          setTextContent(prev => prev.concat({
            sequence: (message as any).sequence,
            content: parsedContent.content,
          }));
          callbacks.onAssistantChunk?.({ content: parsedContent.content });
        } else if (parsedMetadata.stream_status === 'complete') {
          setTextContent([]);
          setToolCall(null);
          if (message.message_id) {
            callbacks.onMessage(message);
          }
        } else if (!parsedMetadata.stream_status) {
          callbacks.onAssistantStart?.();
          if (message.message_id) {
            callbacks.onMessage(message);
          }
        }
        break;
        
      case 'tool_call':
        setToolCall(parsedContent);
        updateProgress({ currentStep: 'Running tools' });
        if (message.message_id) {
          callbacks.onMessage(message);
        }
        break;
        
      default:
        if (message.message_id) {
          callbacks.onMessage(message);
        }
        break;
    }
  }, [status, updateConnectionHealth, updateProgress, addError, callbacks]);
  
  // Start streaming function
  const startStreaming = useCallback((runId: string) => {
    if (!isMountedRef.current) return;
    
    // Clean up existing stream
    if (streamCleanupRef.current) {
      streamCleanupRef.current();
    }
    
    setAgentRunId(runId);
    currentRunIdRef.current = runId;
    setStatus('connecting');
    setError(null);
    
    // Reset enhanced state
    setStreamState(prev => ({
      ...prev,
      progress: {
        percentage: 0,
        currentStep: 'Connecting...',
        completedSteps: [],
      },
      retryCount: 0,
      isRecovering: false,
      connectionHealth: {
        ...prev.connectionHealth,
        status: 'healthy',
        lastHeartbeat: Date.now(),
        reconnectAttempts: 0,
      },
    }));
    
    // Start monitoring
    startHeartbeat();
    startStatusPolling();
    
    // Set up stream
    try {
      const cleanup = streamAgent(runId, handleStreamMessage, (error) => {
        console.error('Stream error:', error);
        addError(error);
        updateConnectionHealth({ status: 'disconnected' });
      });
      
      streamCleanupRef.current = cleanup;
      
      updateProgress({ currentStep: 'Stream connected' });
      
    } catch (error) {
      console.error('Failed to start stream:', error);
      addError(`Failed to start stream: ${error}`);
      setStatus('error');
    }
  }, [handleStreamMessage, addError, updateConnectionHealth, updateProgress, startHeartbeat, startStatusPolling]);
  
  // Stop streaming function
  const stopStreaming = useCallback(async () => {
    if (!isMountedRef.current || !currentRunIdRef.current) return;
    
    try {
      await stopAgent(currentRunIdRef.current);
      
      // Clean up
      if (streamCleanupRef.current) {
        streamCleanupRef.current();
        streamCleanupRef.current = null;
      }
      
      if (heartbeatIntervalRef.current) {
        clearInterval(heartbeatIntervalRef.current);
        heartbeatIntervalRef.current = null;
      }
      
      if (statusPollIntervalRef.current) {
        clearInterval(statusPollIntervalRef.current);
        statusPollIntervalRef.current = null;
      }
      
      setStatus('stopped');
      setAgentRunId(null);
      currentRunIdRef.current = null;
      
      updateProgress({ percentage: 0, currentStep: 'Stopped' });
      callbacks.onClose?.('stopped');
      
    } catch (error) {
      console.error('Failed to stop agent:', error);
      addError(`Failed to stop agent: ${error}`);
    }
  }, [updateProgress, callbacks, addError]);
  
  // Clear errors function
  const clearErrors = useCallback(() => {
    setStreamState(prev => ({
      ...prev,
      errorHistory: [],
    }));
    setError(null);
  }, []);
  
  return {
    // Basic state
    status,
    textContent: orderedTextContent,
    toolCall,
    error,
    agentRunId,
    
    // Enhanced state
    streamState,
    
    // Actions
    startStreaming,
    stopStreaming,
    retryConnection,
    clearErrors,
  };
}