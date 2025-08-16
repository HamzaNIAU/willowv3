import React, { useState, useEffect } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Progress } from '@/components/ui/progress';
import { 
  Activity, 
  Database, 
  Zap, 
  Shield, 
  RefreshCw, 
  AlertTriangle,
  CheckCircle,
  XCircle,
  TrendingUp,
  Clock,
  Users,
  Server
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { enhancedApiClient } from '@/lib/api-client-enhanced';

interface SystemHealth {
  status: 'healthy' | 'degraded' | 'unhealthy' | 'unknown';
  timestamp: string;
  components: {
    redis: ComponentHealth;
    llm: ComponentHealth;
    database: ComponentHealth;
    sandbox: ComponentHealth;
  };
  metrics: {
    totalRequests: number;
    averageResponseTime: number;
    successRate: number;
    activeUsers: number;
    queueLength: number;
  };
}

interface ComponentHealth {
  status: 'healthy' | 'degraded' | 'unhealthy' | 'unknown';
  responseTime?: number;
  successRate?: number;
  details?: Record<string, any>;
  lastCheck?: string;
}

interface SystemHealthDashboardProps {
  refreshInterval?: number;
  compact?: boolean;
  className?: string;
}

const COMPONENT_CONFIGS = {
  redis: {
    name: 'Redis Cache',
    icon: Database,
    description: 'Caching and session management',
    endpoint: '/api/health/redis',
  },
  llm: {
    name: 'LLM Service',
    icon: Zap,
    description: 'AI model processing',
    endpoint: '/api/health/llm',
  },
  database: {
    name: 'Database',
    icon: Server,
    description: 'Data storage and retrieval',
    endpoint: '/api/health',
  },
  sandbox: {
    name: 'Sandbox',
    icon: Shield,
    description: 'Code execution environment',
    endpoint: '/api/health',
  },
};

function getStatusColor(status: string): string {
  switch (status) {
    case 'healthy': return 'text-green-600 bg-green-50 border-green-200';
    case 'degraded': return 'text-yellow-600 bg-yellow-50 border-yellow-200';
    case 'unhealthy': return 'text-red-600 bg-red-50 border-red-200';
    default: return 'text-gray-600 bg-gray-50 border-gray-200';
  }
}

function getStatusIcon(status: string): React.ComponentType<{ className?: string }> {
  switch (status) {
    case 'healthy': return CheckCircle;
    case 'degraded': return AlertTriangle;
    case 'unhealthy': return XCircle;
    default: return Activity;
  }
}

export function SystemHealthDashboard({
  refreshInterval = 30000,
  compact = false,
  className,
}: SystemHealthDashboardProps) {
  const [health, setHealth] = useState<SystemHealth | null>(null);
  const [loading, setLoading] = useState(true);
  const [lastRefresh, setLastRefresh] = useState<Date | null>(null);
  const [error, setError] = useState<string | null>(null);

  const fetchHealth = async () => {
    try {
      setError(null);
      
      // Fetch health data from multiple endpoints
      const [redisHealth, llmHealth, generalHealth] = await Promise.allSettled([
        enhancedApiClient.get('/api/health/redis'),
        enhancedApiClient.get('/api/health/llm'),
        enhancedApiClient.get('/api/health'),
      ]);
      
      // Parse results
      const redis: ComponentHealth = {
        status: redisHealth.status === 'fulfilled' && redisHealth.value.status === 'healthy' ? 'healthy' : 'unhealthy',
        details: redisHealth.status === 'fulfilled' ? redisHealth.value : undefined,
      };
      
      const llm: ComponentHealth = {
        status: llmHealth.status === 'fulfilled' && llmHealth.value.status === 'healthy' ? 'healthy' : 'unhealthy',
        details: llmHealth.status === 'fulfilled' ? llmHealth.value : undefined,
      };
      
      const database: ComponentHealth = {
        status: generalHealth.status === 'fulfilled' && generalHealth.value.status === 'ok' ? 'healthy' : 'unhealthy',
        details: generalHealth.status === 'fulfilled' ? generalHealth.value : undefined,
      };
      
      const sandbox: ComponentHealth = {
        status: generalHealth.status === 'fulfilled' ? 'healthy' : 'unknown',
        details: generalHealth.status === 'fulfilled' ? generalHealth.value : undefined,
      };
      
      // Determine overall status
      const componentStatuses = [redis.status, llm.status, database.status, sandbox.status];
      let overallStatus: SystemHealth['status'] = 'healthy';
      
      if (componentStatuses.includes('unhealthy')) {
        overallStatus = 'unhealthy';
      } else if (componentStatuses.includes('degraded')) {
        overallStatus = 'degraded';
      } else if (componentStatuses.includes('unknown')) {
        overallStatus = 'degraded';
      }
      
      // Mock metrics (in real implementation, these would come from your monitoring system)
      const metrics = {
        totalRequests: Math.floor(Math.random() * 10000) + 1000,
        averageResponseTime: Math.floor(Math.random() * 500) + 100,
        successRate: 95 + Math.random() * 5,
        activeUsers: Math.floor(Math.random() * 100) + 10,
        queueLength: Math.floor(Math.random() * 5),
      };
      
      setHealth({
        status: overallStatus,
        timestamp: new Date().toISOString(),
        components: { redis, llm, database, sandbox },
        metrics,
      });
      
      setLastRefresh(new Date());
      
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch health data');
      console.error('Health check failed:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchHealth();
    
    const interval = setInterval(fetchHealth, refreshInterval);
    return () => clearInterval(interval);
  }, [refreshInterval]);

  if (loading && !health) {
    return (
      <Card className={className}>
        <CardContent className="flex items-center justify-center p-6">
          <div className="flex items-center space-x-2">
            <RefreshCw className="w-4 h-4 animate-spin" />
            <span>Loading system health...</span>
          </div>
        </CardContent>
      </Card>
    );
  }

  if (error && !health) {
    return (
      <Card className={className}>
        <CardContent className="flex items-center justify-center p-6">
          <div className="text-center space-y-2">
            <AlertTriangle className="w-8 h-8 text-red-500 mx-auto" />
            <p className="text-sm text-gray-600">Failed to load system health</p>
            <Button size="sm" onClick={fetchHealth}>Retry</Button>
          </div>
        </CardContent>
      </Card>
    );
  }

  if (!health) return null;

  const StatusIcon = getStatusIcon(health.status);

  if (compact) {
    return (
      <div className={cn('flex items-center space-x-4', className)}>
        <div className="flex items-center space-x-2">
          <StatusIcon className={cn('w-4 h-4', getStatusColor(health.status).split(' ')[0])} />
          <Badge variant="secondary" className={getStatusColor(health.status)}>
            System {health.status}
          </Badge>
        </div>
        
        <div className="flex items-center space-x-4 text-sm text-gray-600">
          <div className="flex items-center space-x-1">
            <TrendingUp className="w-3 h-3" />
            <span>{health.metrics.successRate.toFixed(1)}%</span>
          </div>
          <div className="flex items-center space-x-1">
            <Clock className="w-3 h-3" />
            <span>{health.metrics.averageResponseTime}ms</span>
          </div>
          <div className="flex items-center space-x-1">
            <Users className="w-3 h-3" />
            <span>{health.metrics.activeUsers}</span>
          </div>
        </div>
        
        <Button
          variant="ghost"
          size="sm"
          onClick={fetchHealth}
          disabled={loading}
        >
          <RefreshCw className={cn('w-3 h-3', loading && 'animate-spin')} />
        </Button>
      </div>
    );
  }

  return (
    <Card className={className}>
      <CardHeader>
        <div className="flex items-center justify-between">
          <div className="flex items-center space-x-3">
            <StatusIcon className={cn('w-6 h-6', getStatusColor(health.status).split(' ')[0])} />
            <div>
              <CardTitle className="text-lg">System Health</CardTitle>
              {lastRefresh && (
                <p className="text-sm text-gray-600">
                  Last updated: {lastRefresh.toLocaleTimeString()}
                </p>
              )}
            </div>
          </div>
          
          <div className="flex items-center space-x-2">
            <Badge variant="secondary" className={getStatusColor(health.status)}>
              {health.status.toUpperCase()}
            </Badge>
            <Button
              variant="outline"
              size="sm"
              onClick={fetchHealth}
              disabled={loading}
            >
              <RefreshCw className={cn('w-4 h-4', loading && 'animate-spin')} />
            </Button>
          </div>
        </div>
      </CardHeader>
      
      <CardContent className="space-y-6">
        {/* Key Metrics */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <div className="text-center">
            <div className="text-2xl font-bold text-green-600">
              {health.metrics.successRate.toFixed(1)}%
            </div>
            <div className="text-sm text-gray-600">Success Rate</div>
          </div>
          
          <div className="text-center">
            <div className="text-2xl font-bold text-blue-600">
              {health.metrics.averageResponseTime}ms
            </div>
            <div className="text-sm text-gray-600">Avg Response</div>
          </div>
          
          <div className="text-center">
            <div className="text-2xl font-bold text-purple-600">
              {health.metrics.activeUsers}
            </div>
            <div className="text-sm text-gray-600">Active Users</div>
          </div>
          
          <div className="text-center">
            <div className="text-2xl font-bold text-orange-600">
              {health.metrics.queueLength}
            </div>
            <div className="text-sm text-gray-600">Queue Length</div>
          </div>
        </div>
        
        {/* Component Status */}
        <div>
          <h4 className="font-medium text-gray-900 mb-3">Component Status</h4>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {Object.entries(health.components).map(([key, component]) => {
              const config = COMPONENT_CONFIGS[key as keyof typeof COMPONENT_CONFIGS];
              const ComponentIcon = config.icon;
              const ComponentStatusIcon = getStatusIcon(component.status);
              
              return (
                <div
                  key={key}
                  className={cn(
                    'flex items-center justify-between p-3 rounded-lg border',
                    getStatusColor(component.status)
                  )}
                >
                  <div className="flex items-center space-x-3">
                    <ComponentIcon className="w-5 h-5" />
                    <div>
                      <div className="font-medium">{config.name}</div>
                      <div className="text-xs opacity-75">{config.description}</div>
                    </div>
                  </div>
                  
                  <ComponentStatusIcon className="w-4 h-4" />
                </div>
              );
            })}
          </div>
        </div>
        
        {/* Success Rate Progress */}
        <div>
          <div className="flex items-center justify-between mb-2">
            <span className="text-sm font-medium">Overall Success Rate</span>
            <span className="text-sm text-gray-600">{health.metrics.successRate.toFixed(1)}%</span>
          </div>
          <Progress value={health.metrics.successRate} className="h-2" />
        </div>
        
        {error && (
          <div className="flex items-center space-x-2 p-3 bg-yellow-50 border border-yellow-200 rounded-lg">
            <AlertTriangle className="w-4 h-4 text-yellow-600" />
            <p className="text-sm text-yellow-700">{error}</p>
          </div>
        )}
      </CardContent>
    </Card>
  );
}