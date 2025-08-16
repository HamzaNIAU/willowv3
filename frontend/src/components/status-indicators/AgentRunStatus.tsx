import React, { useState, useEffect } from 'react';
import { Progress } from '@/components/ui/progress';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip';
import { 
  Play, 
  Pause, 
  Square, 
  Clock, 
  Zap, 
  AlertTriangle, 
  CheckCircle, 
  XCircle,
  Loader2,
  Activity,
  Timer
} from 'lucide-react';
import { cn } from '@/lib/utils';

interface AgentRunStatusProps {
  status: string;
  progress?: number;
  currentStep?: string;
  estimatedTimeRemaining?: number;
  queuePosition?: number;
  error?: string | null;
  onStop?: () => void;
  onRetry?: () => void;
  className?: string;
}

interface StatusConfig {
  icon: React.ComponentType<{ className?: string }>;
  color: string;
  bgColor: string;
  textColor: string;
  label: string;
  description: string;
  showProgress: boolean;
  isActive: boolean;
}

const STATUS_CONFIGS: Record<string, StatusConfig> = {
  idle: {
    icon: Clock,
    color: 'border-gray-300 bg-gray-50',
    bgColor: 'bg-gray-50',
    textColor: 'text-gray-700',
    label: 'Idle',
    description: 'Ready to start',
    showProgress: false,
    isActive: false,
  },
  queued: {
    icon: Clock,
    color: 'border-blue-300 bg-blue-50',
    bgColor: 'bg-blue-50',
    textColor: 'text-blue-700',
    label: 'Queued',
    description: 'Waiting in queue',
    showProgress: true,
    isActive: true,
  },
  initializing: {
    icon: Loader2,
    color: 'border-blue-300 bg-blue-50',
    bgColor: 'bg-blue-50',
    textColor: 'text-blue-700',
    label: 'Initializing',
    description: 'Starting up',
    showProgress: true,
    isActive: true,
  },
  loading_agent: {
    icon: Loader2,
    color: 'border-blue-300 bg-blue-50',
    bgColor: 'bg-blue-50',
    textColor: 'text-blue-700',
    label: 'Loading Agent',
    description: 'Loading agent configuration',
    showProgress: true,
    isActive: true,
  },
  loading_tools: {
    icon: Loader2,
    color: 'border-blue-300 bg-blue-50',
    bgColor: 'bg-blue-50',
    textColor: 'text-blue-700',
    label: 'Loading Tools',
    description: 'Loading tools and capabilities',
    showProgress: true,
    isActive: true,
  },
  executing: {
    icon: Play,
    color: 'border-green-300 bg-green-50',
    bgColor: 'bg-green-50',
    textColor: 'text-green-700',
    label: 'Running',
    description: 'Processing your request',
    showProgress: true,
    isActive: true,
  },
  tool_running: {
    icon: Zap,
    color: 'border-amber-300 bg-amber-50',
    bgColor: 'bg-amber-50',
    textColor: 'text-amber-700',
    label: 'Using Tools',
    description: 'Running tools and functions',
    showProgress: true,
    isActive: true,
  },
  streaming: {
    icon: Activity,
    color: 'border-green-300 bg-green-50',
    bgColor: 'bg-green-50',
    textColor: 'text-green-700',
    label: 'Responding',
    description: 'Generating response',
    showProgress: true,
    isActive: true,
  },
  completed: {
    icon: CheckCircle,
    color: 'border-green-300 bg-green-50',
    bgColor: 'bg-green-50',
    textColor: 'text-green-700',
    label: 'Completed',
    description: 'Successfully finished',
    showProgress: false,
    isActive: false,
  },
  failed: {
    icon: XCircle,
    color: 'border-red-300 bg-red-50',
    bgColor: 'bg-red-50',
    textColor: 'text-red-700',
    label: 'Failed',
    description: 'Execution failed',
    showProgress: false,
    isActive: false,
  },
  stopped: {
    icon: Square,
    color: 'border-gray-300 bg-gray-50',
    bgColor: 'bg-gray-50',
    textColor: 'text-gray-700',
    label: 'Stopped',
    description: 'Execution stopped',
    showProgress: false,
    isActive: false,
  },
  error: {
    icon: AlertTriangle,
    color: 'border-red-300 bg-red-50',
    bgColor: 'bg-red-50',
    textColor: 'text-red-700',
    label: 'Error',
    description: 'An error occurred',
    showProgress: false,
    isActive: false,
  },
};

function formatTimeRemaining(seconds: number): string {
  if (seconds < 60) {
    return `${Math.round(seconds)}s`;
  } else if (seconds < 3600) {
    return `${Math.round(seconds / 60)}m`;
  } else {
    return `${Math.round(seconds / 3600)}h`;
  }
}

export function AgentRunStatus({
  status,
  progress = 0,
  currentStep,
  estimatedTimeRemaining,
  queuePosition,
  error,
  onStop,
  onRetry,
  className,
}: AgentRunStatusProps) {
  const [animatedProgress, setAnimatedProgress] = useState(progress);
  
  // Animate progress changes
  useEffect(() => {
    const timer = setTimeout(() => {
      setAnimatedProgress(progress);
    }, 100);
    
    return () => clearTimeout(timer);
  }, [progress]);
  
  const config = STATUS_CONFIGS[status] || STATUS_CONFIGS.error;
  const IconComponent = config.icon;
  
  return (
    <TooltipProvider>
      <div className={cn('space-y-3', className)}>
        {/* Status Header */}
        <div className="flex items-center justify-between">
          <div className="flex items-center space-x-3">
            {/* Status Icon */}
            <div className={cn(
              'flex items-center justify-center w-8 h-8 rounded-full border-2',
              config.color
            )}>
              <IconComponent 
                className={cn(
                  'w-4 h-4',
                  config.textColor,
                  config.isActive && config.icon === Loader2 && 'animate-spin'
                )} 
              />
            </div>
            
            {/* Status Text */}
            <div>
              <div className="flex items-center space-x-2">
                <Badge variant="secondary" className={cn(config.bgColor, config.textColor)}>
                  {config.label}
                </Badge>
                
                {/* Queue Position */}
                {queuePosition !== undefined && queuePosition > 0 && (
                  <Tooltip>
                    <TooltipTrigger>
                      <Badge variant="outline" className="text-xs">
                        #{queuePosition}
                      </Badge>
                    </TooltipTrigger>
                    <TooltipContent>
                      Position in queue
                    </TooltipContent>
                  </Tooltip>
                )}
                
                {/* Estimated Time */}
                {estimatedTimeRemaining && estimatedTimeRemaining > 0 && (
                  <Tooltip>
                    <TooltipTrigger>
                      <div className="flex items-center space-x-1 text-xs text-gray-500">
                        <Timer className="w-3 h-3" />
                        <span>{formatTimeRemaining(estimatedTimeRemaining)}</span>
                      </div>
                    </TooltipTrigger>
                    <TooltipContent>
                      Estimated time remaining
                    </TooltipContent>
                  </Tooltip>
                )}
              </div>
              
              {/* Current Step or Description */}
              <p className="text-sm text-gray-600 mt-1">
                {currentStep || config.description}
              </p>
            </div>
          </div>
          
          {/* Action Buttons */}
          <div className="flex items-center space-x-2">
            {config.isActive && onStop && (
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={onStop}
                    className="h-7 w-7 p-0"
                  >
                    <Square className="w-3 h-3" />
                  </Button>
                </TooltipTrigger>
                <TooltipContent>Stop execution</TooltipContent>
              </Tooltip>
            )}
            
            {(status === 'failed' || status === 'error') && onRetry && (
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={onRetry}
                    className="h-7 w-7 p-0"
                  >
                    <Play className="w-3 h-3" />
                  </Button>
                </TooltipTrigger>
                <TooltipContent>Retry execution</TooltipContent>
              </Tooltip>
            )}
          </div>
        </div>
        
        {/* Progress Bar */}
        {config.showProgress && (
          <div className="space-y-1">
            <Progress 
              value={animatedProgress} 
              className="h-2"
            />
            <div className="flex justify-between text-xs text-gray-500">
              <span>{animatedProgress}% complete</span>
              {estimatedTimeRemaining && estimatedTimeRemaining > 0 && (
                <span>{formatTimeRemaining(estimatedTimeRemaining)} remaining</span>
              )}
            </div>
          </div>
        )}
        
        {/* Error Message */}
        {error && (
          <div className="flex items-start space-x-2 p-3 bg-red-50 border border-red-200 rounded-lg">
            <AlertTriangle className="w-4 h-4 text-red-600 mt-0.5 flex-shrink-0" />
            <div className="text-sm text-red-700">
              <p className="font-medium">Error Details</p>
              <p className="mt-1">{error}</p>
            </div>
          </div>
        )}
      </div>
    </TooltipProvider>
  );
}

// Compact version for smaller spaces
export function CompactAgentRunStatus({
  status,
  progress = 0,
  className,
}: Pick<AgentRunStatusProps, 'status' | 'progress' | 'className'>) {
  const config = STATUS_CONFIGS[status] || STATUS_CONFIGS.error;
  const IconComponent = config.icon;
  
  return (
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger asChild>
          <div className={cn('flex items-center space-x-2', className)}>
            <div className={cn(
              'flex items-center justify-center w-6 h-6 rounded-full border',
              config.color
            )}>
              <IconComponent 
                className={cn(
                  'w-3 h-3',
                  config.textColor,
                  config.isActive && config.icon === Loader2 && 'animate-spin'
                )} 
              />
            </div>
            
            {config.showProgress && (
              <div className="flex-1 min-w-[60px]">
                <Progress value={progress} className="h-1.5" />
              </div>
            )}
            
            <Badge variant="secondary" className={cn('text-xs', config.bgColor, config.textColor)}>
              {config.label}
            </Badge>
          </div>
        </TooltipTrigger>
        <TooltipContent>
          <div className="space-y-1">
            <p className="font-medium">{config.label}</p>
            <p className="text-xs">{config.description}</p>
            {config.showProgress && (
              <p className="text-xs">{progress}% complete</p>
            )}
          </div>
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}