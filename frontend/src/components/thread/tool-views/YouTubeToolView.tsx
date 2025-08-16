'use client'

import React from 'react';
import {
  Youtube,
  Users,
  Eye,
  Video,
  CheckCircle,
  Copy,
  ExternalLink,
  TrendingUp,
  Clock,
  PlayCircle
} from 'lucide-react';
import { ToolViewProps } from './types';
import { formatTimestamp, getToolTitle, extractToolData } from './utils';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { ScrollArea } from "@/components/ui/scroll-area";
import { LoadingState } from './shared/LoadingState';
import { toast } from 'sonner';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip';

interface YouTubeChannel {
  id: string;
  name: string;
  username?: string;
  profile_picture?: string;
  subscriber_count?: number;
  view_count?: number;
  video_count?: number;
}

function formatNumber(num: number | undefined): string {
  if (!num) return '0';
  if (num >= 1000000) {
    return (num / 1000000).toFixed(1).replace(/\.0$/, '') + 'M';
  }
  if (num >= 1000) {
    return (num / 1000).toFixed(1).replace(/\.0$/, '') + 'K';
  }
  return num.toString();
}

function formatLargeNumber(num: number | undefined): string {
  if (!num) return '0';
  return num.toLocaleString();
}

export function YouTubeToolView({
  name = 'youtube-channels',
  assistantContent,
  toolContent,
  assistantTimestamp,
  toolTimestamp,
  isSuccess = true,
  isStreaming = false,
}: ToolViewProps) {
  const [copiedId, setCopiedId] = React.useState<string | null>(null);

  const handleCopyChannelId = (channelId: string) => {
    navigator.clipboard.writeText(channelId);
    setCopiedId(channelId);
    toast.success('Channel ID copied to clipboard');
    setTimeout(() => setCopiedId(null), 2000);
  };

  // Extract the tool data
  const { toolResult } = extractToolData(toolContent);
  
  if (isStreaming || !toolResult?.toolOutput) {
    return <LoadingState title="Fetching YouTube channels..." />;
  }

  // Parse the output
  let channels: YouTubeChannel[] = [];
  let message = '';
  
  try {
    const output = toolResult.toolOutput;
    if (typeof output === 'string') {
      const parsed = JSON.parse(output);
      channels = parsed.channels || [];
      message = parsed.message || '';
    } else if (typeof output === 'object' && output !== null) {
      const outputObj = output as any;
      channels = outputObj.channels || [];
      message = outputObj.message || '';
    }
  } catch (e) {
    console.error('Failed to parse YouTube channels data:', e);
    channels = [];
  }

  const hasChannels = channels.length > 0;

  return (
    <Card className="overflow-hidden border-zinc-200 dark:border-zinc-700 shadow-lg">
      {/* Header */}
      <CardHeader className="pb-4 bg-gradient-to-r from-red-600 to-red-700 dark:from-red-800 dark:to-red-900">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            {/* YouTube Logo */}
            <div className="flex items-center justify-center w-10 h-10 bg-white rounded-lg shadow-md p-1.5">
              <img 
                src="/platforms/youtube.svg" 
                alt="YouTube"
                className="w-full h-full object-contain"
              />
            </div>
            <div>
              <CardTitle className="text-lg font-bold text-white flex items-center gap-2">
                YouTube Channels
              </CardTitle>
              {toolTimestamp && (
                <p className="text-xs text-red-100 mt-0.5">
                  {formatTimestamp(toolTimestamp)}
                </p>
              )}
            </div>
          </div>
          <div className="flex items-center gap-2">
            {isSuccess && (
              <Badge className="bg-green-500 text-white border-0 hover:bg-green-600">
                <CheckCircle className="h-3 w-3 mr-1" />
                Connected
              </Badge>
            )}
            <Badge className="bg-white/20 text-white border-white/30 backdrop-blur-sm">
              {channels.length} {channels.length === 1 ? 'Channel' : 'Channels'}
            </Badge>
          </div>
        </div>
      </CardHeader>

      {/* Content */}
      <CardContent className="p-4">
        {!hasChannels ? (
          <div className="text-center py-8">
            <Youtube className="h-12 w-12 mx-auto text-zinc-400 mb-3" />
            <p className="text-sm text-zinc-600 dark:text-zinc-400">
              No YouTube channels connected yet
            </p>
            <p className="text-xs text-zinc-500 dark:text-zinc-500 mt-1">
              Use the authenticate command to connect your YouTube account
            </p>
          </div>
        ) : (
          <ScrollArea className="max-h-[500px]">
            <div className="space-y-4">
              {channels.map((channel) => (
                <Card 
                  key={channel.id} 
                  className="overflow-hidden bg-gradient-to-r from-zinc-50 to-zinc-100 dark:from-zinc-900 dark:to-zinc-800 border border-zinc-200 dark:border-zinc-700 hover:shadow-xl transition-all duration-300"
                >
                  <div className="flex items-stretch">
                    {/* Left side - Avatar and main info */}
                    <div className="flex items-center gap-4 p-5 flex-1">
                      {/* Channel Avatar */}
                      <div className="shrink-0 relative">
                        {channel.profile_picture ? (
                          <div className="relative group">
                            <img
                              src={channel.profile_picture}
                              alt={channel.name}
                              className="w-20 h-20 rounded-full border-3 border-white dark:border-zinc-700 shadow-lg object-cover"
                              onError={(e) => {
                                const target = e.target as HTMLImageElement;
                                target.onerror = null;
                                target.src = 'data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iODAiIGhlaWdodD0iODAiIHZpZXdCb3g9IjAgMCA4MCA4MCIgZmlsbD0ibm9uZSIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj4KPHJlY3Qgd2lkdGg9IjgwIiBoZWlnaHQ9IjgwIiByeD0iNDAiIGZpbGw9IiNGRjAwMDAiLz4KPHBhdGggZD0iTTU1IDQwTDMzIDI4VjUyTDU1IDQwWiIgZmlsbD0id2hpdGUiLz4KPC9zdmc+';
                              }}
                            />
                            <div className="absolute -bottom-1 -right-1 w-7 h-7 bg-white dark:bg-zinc-900 rounded-full flex items-center justify-center shadow-md border border-zinc-200 dark:border-zinc-700 p-1">
                              <img 
                                src="/platforms/youtube.svg" 
                                alt="YouTube"
                                className="w-full h-full object-contain"
                              />
                            </div>
                          </div>
                        ) : (
                          <div className="w-20 h-20 rounded-full bg-gradient-to-br from-red-500 to-red-700 flex items-center justify-center shadow-lg">
                            <Youtube className="h-10 w-10 text-white" />
                          </div>
                        )}
                      </div>

                      {/* Channel Info */}
                      <div className="flex-1 min-w-0">
                        <div className="flex items-start justify-between">
                          <div>
                            <h4 className="text-lg font-bold text-zinc-900 dark:text-zinc-100">
                              {channel.name}
                            </h4>
                            {channel.username && (
                              <p className="text-sm text-zinc-600 dark:text-zinc-400 flex items-center gap-1">
                                <span className="text-zinc-400">@</span>{channel.username}
                              </p>
                            )}
                            
                            {/* Stats Row */}
                            <div className="flex flex-wrap items-center gap-4 mt-3">
                              <div className="flex items-center gap-1.5">
                                <Users className="h-4 w-4 text-red-600 dark:text-red-500" />
                                <span className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">
                                  {formatNumber(channel.subscriber_count)}
                                </span>
                                <span className="text-xs text-zinc-500">subscribers</span>
                              </div>

                              <div className="flex items-center gap-1.5">
                                <Eye className="h-4 w-4 text-blue-600 dark:text-blue-500" />
                                <span className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">
                                  {formatNumber(channel.view_count)}
                                </span>
                                <span className="text-xs text-zinc-500">views</span>
                              </div>

                              <div className="flex items-center gap-1.5">
                                <PlayCircle className="h-4 w-4 text-green-600 dark:text-green-500" />
                                <span className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">
                                  {channel.video_count}
                                </span>
                                <span className="text-xs text-zinc-500">videos</span>
                              </div>
                            </div>
                          </div>
                        </div>
                      </div>
                    </div>

                    {/* Right side - Action buttons */}
                    <div className="flex flex-col justify-center gap-2 p-4 bg-gradient-to-l from-zinc-100 to-transparent dark:from-zinc-800 dark:to-transparent">
                      <Button
                        className="bg-red-600 hover:bg-red-700 text-white font-medium px-4 py-2 flex items-center gap-2 shadow-md"
                        onClick={() => window.open(`https://youtube.com/channel/${channel.id}`, '_blank')}
                      >
                        <img 
                          src="/platforms/youtube.svg" 
                          alt="YouTube"
                          className="h-4 w-4 object-contain brightness-0 invert"
                        />
                        View Channel
                      </Button>
                      
                      <Button
                        variant="outline"
                        className="border-zinc-300 dark:border-zinc-600 hover:bg-zinc-100 dark:hover:bg-zinc-700"
                        onClick={() => handleCopyChannelId(channel.id)}
                      >
                        {copiedId === channel.id ? (
                          <>
                            <CheckCircle className="h-4 w-4 text-green-600 mr-2" />
                            Copied!
                          </>
                        ) : (
                          <>
                            <Copy className="h-4 w-4 mr-2" />
                            Copy ID
                          </>
                        )}
                      </Button>
                    </div>
                  </div>
                </Card>
              ))}
            </div>
          </ScrollArea>
        )}

        {/* Summary Message */}
        {message && (
          <div className="mt-4 p-3 bg-zinc-50 dark:bg-zinc-900/50 rounded-lg border border-zinc-200 dark:border-zinc-700">
            <p className="text-sm text-zinc-600 dark:text-zinc-400">
              {message}
            </p>
          </div>
        )}
      </CardContent>
    </Card>
  );
}