import React, { useState, useEffect } from 'react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip';
import { 
  Wifi, 
  WifiOff, 
  Signal, 
  SignalHigh, 
  SignalMedium, 
  SignalLow,
  RefreshCw,
  AlertTriangle,
  CheckCircle
} from 'lucide-react';
import { cn } from '@/lib/utils';

interface ConnectionHealthProps {
  status: 'healthy' | 'degraded' | 'disconnected' | 'connecting';
  latency?: number;
  lastHeartbeat?: number;
  reconnectAttempts?: number;
  onRetry?: () => void;
  className?: string;
}

interface HealthConfig {
  icon: React.ComponentType<{ className?: string }>;
  color: string;
  bgColor: string;
  textColor: string;
  label: string;
  description: string;
  showLatency: boolean;
}

const HEALTH_CONFIGS: Record<string, HealthConfig> = {
  healthy: {
    icon: CheckCircle,
    color: 'border-green-300 bg-green-50',
    bgColor: 'bg-green-50',
    textColor: 'text-green-700',
    label: 'Connected',
    description: 'Connection is stable',
    showLatency: true,
  },
  degraded: {
    icon: SignalMedium,
    color: 'border-yellow-300 bg-yellow-50',
    bgColor: 'bg-yellow-50',
    textColor: 'text-yellow-700',
    label: 'Degraded',
    description: 'Connection issues detected',
    showLatency: true,
  },
  disconnected: {
    icon: WifiOff,
    color: 'border-red-300 bg-red-50',
    bgColor: 'bg-red-50',
    textColor: 'text-red-700',
    label: 'Disconnected',
    description: 'No connection',
    showLatency: false,
  },
  connecting: {
    icon: RefreshCw,
    color: 'border-blue-300 bg-blue-50',
    bgColor: 'bg-blue-50',
    textColor: 'text-blue-700',
    label: 'Connecting',
    description: 'Establishing connection',
    showLatency: false,
  },
};

function getLatencyColor(latency: number): string {
  if (latency < 100) return 'text-green-600';
  if (latency < 300) return 'text-yellow-600';
  if (latency < 1000) return 'text-orange-600';
  return 'text-red-600';
}

function getLatencyIcon(latency: number): React.ComponentType<{ className?: string }> {
  if (latency < 100) return SignalHigh;
  if (latency < 300) return SignalMedium;
  if (latency < 1000) return SignalLow;
  return WifiOff;
}

function formatLatency(latency: number): string {
  if (latency < 1000) {
    return `${Math.round(latency)}ms`;
  } else {
    return `${(latency / 1000).toFixed(1)}s`;
  }
}

function getTimeSinceHeartbeat(lastHeartbeat: number): string {
  const now = Date.now();
  const diff = now - lastHeartbeat;
  
  if (diff < 1000) return 'now';
  if (diff < 60000) return `${Math.round(diff / 1000)}s ago`;
  if (diff < 3600000) return `${Math.round(diff / 60000)}m ago`;
  return `${Math.round(diff / 3600000)}h ago`;
}

export function ConnectionHealth({
  status,
  latency = 0,
  lastHeartbeat,
  reconnectAttempts = 0,
  onRetry,
  className,
}: ConnectionHealthProps) {
  const [currentTime, setCurrentTime] = useState(Date.now());
  
  // Update current time every second for heartbeat display
  useEffect(() => {
    const interval = setInterval(() => {
      setCurrentTime(Date.now());
    }, 1000);
    
    return () => clearInterval(interval);
  }, []);
  
  const config = HEALTH_CONFIGS[status];
  const IconComponent = config.icon;
  const LatencyIcon = latency > 0 ? getLatencyIcon(latency) : Signal;
  
  return (
    <TooltipProvider>
      <div className={cn('flex items-center space-x-2', className)}>
        {/* Connection Status */}
        <Tooltip>
          <TooltipTrigger asChild>
            <div className={cn(
              'flex items-center justify-center w-6 h-6 rounded-full border',
              config.color
            )}>
              <IconComponent 
                className={cn(
                  'w-3.5 h-3.5',
                  config.textColor,
                  status === 'connecting' && 'animate-spin'
                )} 
              />
            </div>
          </TooltipTrigger>
          <TooltipContent>
            <div className="space-y-1">
              <p className="font-medium">{config.label}</p>
              <p className="text-xs">{config.description}</p>
              {lastHeartbeat && (
                <p className="text-xs">
                  Last update: {getTimeSinceHeartbeat(lastHeartbeat)}
                </p>
              )}
              {reconnectAttempts > 0 && (
                <p className="text-xs">
                  Reconnect attempts: {reconnectAttempts}
                </p>
              )}
            </div>
          </TooltipContent>
        </Tooltip>
        
        {/* Latency Indicator */}
        {config.showLatency && latency > 0 && (
          <Tooltip>
            <TooltipTrigger asChild>
              <div className="flex items-center space-x-1">
                <LatencyIcon className={cn('w-3 h-3', getLatencyColor(latency))} />
                <span className={cn('text-xs font-mono', getLatencyColor(latency))}>
                  {formatLatency(latency)}
                </span>
              </div>
            </TooltipTrigger>
            <TooltipContent>
              <div className="space-y-1">
                <p className="font-medium">Connection Latency</p>
                <p className="text-xs">{formatLatency(latency)}</p>
                {latency < 100 && <p className="text-xs text-green-600">Excellent</p>}
                {latency >= 100 && latency < 300 && <p className="text-xs text-yellow-600">Good</p>}
                {latency >= 300 && latency < 1000 && <p className="text-xs text-orange-600">Fair</p>}
                {latency >= 1000 && <p className="text-xs text-red-600">Poor</p>}
              </div>
            </TooltipContent>
          </Tooltip>
        )}
        
        {/* Status Badge */}
        <Badge variant="secondary" className={cn('text-xs', config.bgColor, config.textColor)}>
          {config.label}
        </Badge>
        
        {/* Retry Button */}
        {(status === 'disconnected' || status === 'degraded') && onRetry && (
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant="ghost"
                size="sm"
                onClick={onRetry}
                className="h-6 w-6 p-0"
              >
                <RefreshCw className="w-3 h-3" />
              </Button>
            </TooltipTrigger>
            <TooltipContent>Retry connection</TooltipContent>
          </Tooltip>
        )}
      </div>
    </TooltipProvider>
  );
}

// Minimal version for status bars
export function CompactConnectionHealth({
  status,
  latency,
  className,
}: Pick<ConnectionHealthProps, 'status' | 'latency' | 'className'>) {
  const config = HEALTH_CONFIGS[status];
  const IconComponent = config.icon;
  
  return (
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger asChild>
          <div className={cn('flex items-center space-x-1', className)}>
            <IconComponent 
              className={cn(
                'w-3 h-3',
                config.textColor,
                status === 'connecting' && 'animate-spin'
              )} 
            />
            {config.showLatency && latency && latency > 0 && (
              <span className={cn('text-xs font-mono', getLatencyColor(latency))}>
                {formatLatency(latency)}
              </span>
            )}
          </div>
        </TooltipTrigger>
        <TooltipContent>
          <div className="space-y-1">
            <p className="font-medium">{config.label}</p>
            <p className="text-xs">{config.description}</p>
            {config.showLatency && latency && latency > 0 && (
              <p className="text-xs">Latency: {formatLatency(latency)}</p>
            )}
          </div>
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}

// Hook for monitoring connection health
export function useConnectionHealth() {
  const [status, setStatus] = useState<'healthy' | 'degraded' | 'disconnected' | 'connecting'>('healthy');
  const [latency, setLatency] = useState(0);
  const [lastHeartbeat, setLastHeartbeat] = useState(Date.now());
  const [reconnectAttempts, setReconnectAttempts] = useState(0);
  
  // Monitor online/offline status
  useEffect(() => {
    const handleOnline = () => {
      setStatus('healthy');
      setReconnectAttempts(0);
    };
    
    const handleOffline = () => {
      setStatus('disconnected');
    };
    
    window.addEventListener('online', handleOnline);
    window.addEventListener('offline', handleOffline);
    
    // Set initial status
    setStatus(navigator.onLine ? 'healthy' : 'disconnected');
    
    return () => {
      window.removeEventListener('online', handleOnline);
      window.removeEventListener('offline', handleOffline);
    };
  }, []);
  
  // Test connection function
  const testConnection = async () => {
    const startTime = Date.now();
    setStatus('connecting');
    
    try {
      const response = await fetch('/api/health', {
        method: 'GET',
        cache: 'no-cache',
      });
      
      const endTime = Date.now();
      const measuredLatency = endTime - startTime;
      
      if (response.ok) {
        setLatency(measuredLatency);
        setLastHeartbeat(endTime);
        setStatus(measuredLatency > 1000 ? 'degraded' : 'healthy');
        setReconnectAttempts(0);
      } else {
        setStatus('degraded');
        setReconnectAttempts(prev => prev + 1);
      }
    } catch (error) {
      setStatus('disconnected');
      setReconnectAttempts(prev => prev + 1);
    }
  };
  
  // Regular heartbeat check
  useEffect(() => {
    if (status === 'disconnected') return;
    
    const interval = setInterval(testConnection, 30000); // Test every 30 seconds
    
    // Initial test
    testConnection();
    
    return () => clearInterval(interval);
  }, [status]);
  
  return {
    status,
    latency,
    lastHeartbeat,
    reconnectAttempts,
    testConnection,
  };
}