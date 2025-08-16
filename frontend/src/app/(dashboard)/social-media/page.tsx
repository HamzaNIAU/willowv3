'use client';

import React, { useState, useMemo } from 'react';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Skeleton } from '@/components/ui/skeleton';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { PageHeader } from '@/components/ui/page-header';
import { Input } from '@/components/ui/input';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { 
  Youtube, 
  Instagram, 
  Twitter, 
  Facebook,
  Linkedin,
  Music,
  Video,
  Plus,
  Check,
  X,
  ExternalLink,
  Users,
  Eye,
  PlayCircle,
  AlertCircle,
  Share2,
  Search,
  Settings,
  CheckCircle2,
  XCircle,
  Trash2,
  Copy,
  EyeOff,
  MoreVertical
} from 'lucide-react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { backendApi } from '@/lib/api-client';
import { toast } from 'sonner';

interface YouTubeChannel {
  id: string;
  name: string;
  username?: string;
  profile_picture?: string;
  profile_picture_medium?: string;
  profile_picture_small?: string;
  subscriber_count: number;
  view_count: number;
  video_count: number;
  created_at: string;
}

interface SocialMediaAccount {
  platform: string;
  id: string;
  name: string;
  username?: string;
  profile_picture?: string;
  connected: boolean;
  stats?: {
    followers?: number;
    posts?: number;
    views?: number;
  };
}

const platformIcons = {
  youtube: Youtube,
  instagram: Instagram,
  twitter: Twitter,
  facebook: Facebook,
  linkedin: Linkedin,
  tiktok: Music,
  twitch: Video,
};

const platformColors = {
  youtube: 'hover:bg-red-50 hover:border-red-200 dark:hover:bg-red-950/20',
  instagram: 'hover:bg-pink-50 hover:border-pink-200 dark:hover:bg-pink-950/20',
  twitter: 'hover:bg-blue-50 hover:border-blue-200 dark:hover:bg-blue-950/20',
  facebook: 'hover:bg-blue-50 hover:border-blue-200 dark:hover:bg-blue-950/20',
  linkedin: 'hover:bg-blue-50 hover:border-blue-200 dark:hover:bg-blue-950/20',
  tiktok: 'hover:bg-gray-50 hover:border-gray-200 dark:hover:bg-gray-950/20',
  twitch: 'hover:bg-purple-50 hover:border-purple-200 dark:hover:bg-purple-950/20',
};

interface SocialPlatformGroup {
  name: string;
  icon: any;
  icon_url?: string;
  color: string;
  accounts: YouTubeChannel[];
  available: boolean;
  description: string;
}

export default function SocialMediaPage() {
  const queryClient = useQueryClient();
  const [connectingPlatform, setConnectingPlatform] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [showMcpDialog, setShowMcpDialog] = useState(false);
  const [selectedChannel, setSelectedChannel] = useState<YouTubeChannel | null>(null);

  // Fetch YouTube channels
  const { data: youtubeChannels, isLoading: loadingYouTube } = useQuery({
    queryKey: ['youtube', 'channels'],
    queryFn: async () => {
      const response = await backendApi.get<{ success: boolean; channels: YouTubeChannel[] }>(
        '/youtube/channels'
      );
      return response.data.channels;
    },
  });

  // Initiate YouTube auth
  const initiateYouTubeAuth = useMutation({
    mutationFn: async () => {
      const response = await backendApi.post<{ success: boolean; auth_url: string }>(
        '/youtube/auth/initiate'
      );
      return response.data;
    },
    onSuccess: (data) => {
      if (data.auth_url) {
        // Open OAuth popup
        const popup = window.open(
          data.auth_url,
          'youtube-auth',
          'width=600,height=700,resizable=yes,scrollbars=yes'
        );
        
        // Listen for auth completion
        const handleMessage = (event: MessageEvent) => {
          if (event.data?.type === 'youtube-auth-success') {
            popup?.close();
            queryClient.invalidateQueries({ queryKey: ['youtube', 'channels'] });
            toast.success('YouTube account connected successfully!');
            window.removeEventListener('message', handleMessage);
            setConnectingPlatform(null);
          } else if (event.data?.type === 'youtube-auth-error') {
            popup?.close();
            toast.error(`Failed to connect: ${event.data.error}`);
            window.removeEventListener('message', handleMessage);
            setConnectingPlatform(null);
          }
        };
        
        window.addEventListener('message', handleMessage);
      }
    },
    onError: (error: any) => {
      toast.error(error.message || 'Failed to initiate YouTube authentication');
      setConnectingPlatform(null);
    },
  });

  // Remove YouTube channel
  const removeYouTubeChannel = useMutation({
    mutationFn: async (channelId: string) => {
      await backendApi.delete(`/youtube/channels/${channelId}`);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['youtube', 'channels'] });
      toast.success('YouTube channel disconnected');
    },
    onError: (error: any) => {
      toast.error(error.message || 'Failed to disconnect channel');
    },
  });

  const handleConnectYouTube = () => {
    setConnectingPlatform('youtube');
    initiateYouTubeAuth.mutate();
  };

  const formatCount = (count: number): string => {
    if (count >= 1_000_000) {
      return `${(count / 1_000_000).toFixed(1)}M`;
    } else if (count >= 1_000) {
      return `${(count / 1_000).toFixed(1)}K`;
    }
    return count.toString();
  };

  // Group platforms with their connected accounts
  const socialPlatforms = useMemo((): SocialPlatformGroup[] => {
    const platforms: SocialPlatformGroup[] = [
      {
        name: 'YouTube',
        icon: Youtube,
        color: 'text-red-600 dark:text-red-500',
        accounts: youtubeChannels || [],
        available: true,
        description: 'Upload videos, manage playlists, and analyze channel performance'
      },
      {
        name: 'Instagram',
        icon: Instagram,
        color: 'text-pink-600 dark:text-pink-500',
        accounts: [],
        available: false,
        description: 'Post photos and stories, manage content, and track engagement'
      },
      {
        name: 'X (Twitter)',
        icon: Twitter,
        color: 'text-blue-600 dark:text-blue-500',
        accounts: [],
        available: false,
        description: 'Tweet, schedule posts, and analyze engagement metrics'
      },
      {
        name: 'TikTok',
        icon: Music,
        color: 'text-gray-900 dark:text-gray-100',
        accounts: [],
        available: false,
        description: 'Upload short videos, track trends, and manage content'
      },
      {
        name: 'LinkedIn',
        icon: Linkedin,
        color: 'text-blue-700 dark:text-blue-600',
        accounts: [],
        available: false,
        description: 'Share professional content and manage company pages'
      },
      {
        name: 'Facebook',
        icon: Facebook,
        color: 'text-blue-600 dark:text-blue-500',
        accounts: [],
        available: false,
        description: 'Manage pages, post content, and track engagement'
      },
      {
        name: 'Twitch',
        icon: Video,
        color: 'text-purple-600 dark:text-purple-500',
        accounts: [],
        available: false,
        description: 'Stream management, VOD uploads, and analytics'
      }
    ];

    // Filter based on search
    if (searchQuery) {
      return platforms.filter(p => 
        p.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
        p.accounts.some(a => 
          a.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
          a.username?.toLowerCase().includes(searchQuery.toLowerCase())
        )
      );
    }

    return platforms;
  }, [youtubeChannels, searchQuery]);

  const connectedPlatforms = socialPlatforms.filter(p => p.accounts.length > 0);
  const availablePlatforms = socialPlatforms.filter(p => p.available && p.accounts.length === 0);
  const comingSoonPlatforms = socialPlatforms.filter(p => !p.available);


  return (
    <div className="container mx-auto max-w-4xl px-6 py-6">
      <div className="space-y-8">
        <PageHeader icon={Share2}>
          <span className="text-primary">Social Media Connections</span>
        </PageHeader>

        {/* Search Bar */}
        <div className="relative">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <Input
            placeholder="Search platforms or accounts..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="pl-9 pr-9"
          />
          {searchQuery && (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setSearchQuery('')}
              className="absolute right-1 top-1/2 -translate-y-1/2 h-7 w-7 p-0"
            >
              <X className="h-4 w-4" />
            </Button>
          )}
        </div>

        {/* Connected Platforms */}
        {connectedPlatforms.length > 0 && (
          <div className="space-y-6">
            <h2 className="text-lg font-semibold">Connected Accounts</h2>
            {connectedPlatforms.map((platform) => (
              <Card key={platform.name}>
                <CardHeader className="pb-3">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-3">
                      <div className="h-10 w-10 rounded-lg bg-muted border flex items-center justify-center">
                        <platform.icon className={`h-5 w-5 ${platform.color}`} />
                      </div>
                      <div>
                        <CardTitle className="text-base">{platform.name}</CardTitle>
                        <CardDescription className="text-xs">
                          {platform.accounts.length} {platform.accounts.length === 1 ? 'account' : 'accounts'} connected
                        </CardDescription>
                      </div>
                    </div>
                    <Button
                      onClick={platform.name === 'YouTube' ? handleConnectYouTube : undefined}
                      disabled={!platform.available || connectingPlatform === platform.name.toLowerCase()}
                      size="sm"
                    >
                      <Plus className="h-4 w-4 mr-2" />
                      Add Account
                    </Button>
                  </div>
                </CardHeader>
                <CardContent>
                  {loadingYouTube && platform.name === 'YouTube' ? (
                    <div className="space-y-2">
                      <Skeleton className="h-16 w-full" />
                      <Skeleton className="h-16 w-full" />
                    </div>
                  ) : (
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead>Account</TableHead>
                          <TableHead>Statistics</TableHead>
                          <TableHead>Status</TableHead>
                          <TableHead className="w-[50px]"></TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {platform.accounts.map((channel) => (
                          <TableRow key={channel.id}>
                            <TableCell>
                              <div className="flex items-center gap-3">
                                {(channel.profile_picture_medium || channel.profile_picture || channel.profile_picture_small) ? (
                                  <img
                                    src={channel.profile_picture_medium || channel.profile_picture || channel.profile_picture_small}
                                    alt={channel.name}
                                    className="h-10 w-10 rounded-full object-cover border"
                                    onError={(e) => {
                                      console.error('Failed to load profile picture for:', channel.name, e);
                                      (e.target as HTMLImageElement).style.display = 'none';
                                      (e.target as HTMLImageElement).nextElementSibling?.classList.remove('hidden');
                                    }}
                                  />
                                ) : null}
                                <div className={`h-10 w-10 rounded-full bg-red-100 dark:bg-red-900/20 flex items-center justify-center ${(channel.profile_picture_medium || channel.profile_picture || channel.profile_picture_small) ? 'hidden' : ''}`}>
                                  <Youtube className="h-5 w-5 text-red-600" />
                                </div>
                                <div>
                                  <div className="font-medium">{channel.name}</div>
                                  {channel.username && (
                                    <div className="text-sm text-muted-foreground">@{channel.username}</div>
                                  )}
                                </div>
                              </div>
                            </TableCell>
                            <TableCell>
                              <div className="flex items-center gap-6 text-sm">
                                <div className="flex items-center gap-1">
                                  <Users className="h-3.5 w-3.5 text-muted-foreground" />
                                  <span>{formatCount(channel.subscriber_count)}</span>
                                </div>
                                <div className="flex items-center gap-1">
                                  <Eye className="h-3.5 w-3.5 text-muted-foreground" />
                                  <span>{formatCount(channel.view_count)}</span>
                                </div>
                                <div className="flex items-center gap-1">
                                  <PlayCircle className="h-3.5 w-3.5 text-muted-foreground" />
                                  <span>{channel.video_count}</span>
                                </div>
                              </div>
                            </TableCell>
                            <TableCell>
                              <div className="flex items-center gap-1.5">
                                <CheckCircle2 className="h-4 w-4 text-green-600 dark:text-green-500" />
                                <span className="text-sm text-green-600 dark:text-green-500">Connected</span>
                              </div>
                            </TableCell>
                            <TableCell>
                              <DropdownMenu>
                                <DropdownMenuTrigger asChild>
                                  <Button variant="ghost" size="sm" className="h-8 w-8 p-0">
                                    <MoreVertical className="h-4 w-4" />
                                  </Button>
                                </DropdownMenuTrigger>
                                <DropdownMenuContent align="end">
                                  <DropdownMenuItem 
                                    onClick={() => window.open(`https://youtube.com/channel/${channel.id}`, '_blank')}
                                  >
                                    <ExternalLink className="h-4 w-4 mr-2" />
                                    View Channel
                                  </DropdownMenuItem>
                                  <DropdownMenuItem
                                    onClick={() => {
                                      setSelectedChannel(channel);
                                      setShowMcpDialog(true);
                                    }}
                                  >
                                    <Settings className="h-4 w-4 mr-2" />
                                    MCP Settings
                                  </DropdownMenuItem>
                                  <DropdownMenuSeparator />
                                  <DropdownMenuItem
                                    onClick={() => removeYouTubeChannel.mutate(channel.id)}
                                    className="text-destructive"
                                  >
                                    <Trash2 className="h-4 w-4 mr-2" />
                                    Disconnect
                                  </DropdownMenuItem>
                                </DropdownMenuContent>
                              </DropdownMenu>
                            </TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  )}
                </CardContent>
              </Card>
            ))}
          </div>
        )}

        {/* Available Platforms */}
        {availablePlatforms.length > 0 && (
          <div className="space-y-6">
            <h2 className="text-lg font-semibold">Available Integrations</h2>
            <div className="grid gap-4">
              {availablePlatforms.map((platform) => (
                <Card key={platform.name} className="hover:shadow-sm transition-shadow">
                  <CardContent className="p-6">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-4">
                        <div className="h-12 w-12 rounded-lg bg-muted border flex items-center justify-center">
                          <platform.icon className={`h-6 w-6 ${platform.color}`} />
                        </div>
                        <div className="flex-1">
                          <h3 className="font-semibold">{platform.name}</h3>
                          <p className="text-sm text-muted-foreground">{platform.description}</p>
                        </div>
                      </div>
                      <Button
                        onClick={platform.name === 'YouTube' ? handleConnectYouTube : undefined}
                        disabled={connectingPlatform === platform.name.toLowerCase()}
                      >
                        <Plus className="h-4 w-4 mr-2" />
                        Connect
                      </Button>
                    </div>
                  </CardContent>
                </Card>
              ))}
            </div>
          </div>
        )}

        {/* Coming Soon Platforms */}
        {comingSoonPlatforms.length > 0 && (
          <div className="space-y-6">
            <h2 className="text-lg font-semibold">Coming Soon</h2>
            <div className="grid gap-4 md:grid-cols-2">
              {comingSoonPlatforms.map((platform) => (
                <Card key={platform.name} className="opacity-60">
                  <CardContent className="p-6">
                    <div className="flex items-center gap-4">
                      <div className="h-12 w-12 rounded-lg bg-muted border flex items-center justify-center">
                        <platform.icon className={`h-6 w-6 ${platform.color} opacity-50`} />
                      </div>
                      <div className="flex-1">
                        <h3 className="font-semibold">{platform.name}</h3>
                        <p className="text-sm text-muted-foreground">{platform.description}</p>
                        <p className="text-xs text-muted-foreground mt-1">Integration coming soon</p>
                      </div>
                    </div>
                  </CardContent>
                </Card>
              ))}
            </div>
          </div>
        )}

        {/* MCP URL Dialog */}
        {showMcpDialog && selectedChannel && (
          <Dialog open={showMcpDialog} onOpenChange={setShowMcpDialog}>
            <DialogContent className="max-w-2xl">
              <DialogHeader>
                <DialogTitle className="flex items-center gap-3">
                  <div className="h-14 w-14 rounded-lg bg-muted border flex items-center justify-center overflow-hidden">
                    {selectedChannel.profile_picture ? (
                      <img 
                        src={selectedChannel.profile_picture} 
                        alt={selectedChannel.name}
                        className="h-10 w-10 rounded-full object-cover"
                      />
                    ) : (
                      <Youtube className="h-6 w-6 text-red-600" />
                    )}
                  </div>
                  <div>
                    <span>{selectedChannel.name}</span>
                    <div className="text-sm text-muted-foreground flex items-center gap-1 mt-1">
                      <ExternalLink className="h-3 w-3" />
                      <span>YouTube MCP Settings</span>
                    </div>
                  </div>
                </DialogTitle>
              </DialogHeader>
              <div className="space-y-6">
                <Alert className="border-amber-400/50 dark:border-amber-600/30 bg-amber-400/10 dark:bg-amber-900/10">
                  <AlertDescription className="text-amber-800 dark:text-amber-600">
                    <strong>MCP URL:</strong> Use this URL to configure YouTube tools in your AI agents
                  </AlertDescription>
                </Alert>
                <div className="space-y-3">
                  <label className="text-sm font-medium">MCP Connection URL</label>
                  <div className="flex items-center gap-2 p-3 bg-muted rounded-lg border font-mono text-sm">
                    <code className="flex-1 break-all">
                      http://localhost:8000/api/youtube/mcp/stream
                    </code>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={async () => {
                        await navigator.clipboard.writeText('http://localhost:8000/api/youtube/mcp/stream');
                        toast.success('MCP URL copied to clipboard');
                      }}
                    >
                      <Copy className="h-4 w-4" />
                    </Button>
                  </div>
                </div>
                <div className="flex justify-end gap-3">
                  <Button variant="outline" onClick={() => setShowMcpDialog(false)}>
                    Close
                  </Button>
                </div>
              </div>
            </DialogContent>
          </Dialog>
        )}
      </div>
    </div>
  );
}