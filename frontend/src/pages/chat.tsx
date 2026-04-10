import React, { useState, useEffect, useRef, useCallback } from 'react';
import { useAuth } from '../contexts/AuthContext';
import Navbar from '../components/Navbar';
import {
  MessageCircle, Send, Hash, User, Users, Search, Plus, ArrowLeft, Paperclip, Smile, X,
  Zap, Brain,
} from 'lucide-react';
import axios from 'axios';

const API = process.env.NEXT_PUBLIC_API_URL || 'https://better-choice-api.onrender.com';

function getToken() {
  return localStorage.getItem('token') || '';
}

function headers() {
  return { Authorization: `Bearer ${getToken()}` };
}

function timeAgo(iso: string) {
  if (!iso) return '';
  const d = new Date(iso);
  const now = new Date();
  const diff = (now.getTime() - d.getTime()) / 1000;
  if (diff < 60) return 'just now';
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
}

function formatTime(iso: string) {
  if (!iso) return '';
  return new Date(iso).toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' });
}

function getInitials(name: string) {
  return (name || '?').split(' ').map(w => w[0]).join('').toUpperCase().slice(0, 2);
}

const AVATAR_COLORS = [
  'from-cyan-500 to-blue-600',
  'from-emerald-500 to-teal-600',
  'from-amber-500 to-orange-600',
  'from-purple-500 to-indigo-600',
  'from-pink-500 to-rose-600',
  'from-sky-500 to-cyan-600',
];

function avatarColor(id: number) {
  return AVATAR_COLORS[id % AVATAR_COLORS.length];
}

// BEACON typing indicator component
function BeaconTyping() {
  return (
    <div className="mt-4">
      <div className="flex items-center gap-2 mb-1">
        <div className="w-7 h-7 rounded-full bg-gradient-to-br from-amber-400 to-orange-500 flex items-center justify-center text-[10px] font-bold flex-shrink-0">
          <Zap size={14} className="text-white" />
        </div>
        <span className="text-sm font-semibold text-amber-300">BEACON</span>
        <span className="text-xs text-slate-500">is thinking...</span>
      </div>
      <div className="pl-9">
        <div className="flex items-center gap-1.5">
          <div className="w-2 h-2 rounded-full bg-amber-400 animate-bounce" style={{ animationDelay: '0ms' }} />
          <div className="w-2 h-2 rounded-full bg-amber-400 animate-bounce" style={{ animationDelay: '150ms' }} />
          <div className="w-2 h-2 rounded-full bg-amber-400 animate-bounce" style={{ animationDelay: '300ms' }} />
        </div>
      </div>
    </div>
  );
}

export default function ChatPage() {
  const { user } = useAuth();
  const [channels, setChannels] = useState<any[]>([]);
  const [activeChannel, setActiveChannel] = useState<any>(null);
  const [messages, setMessages] = useState<any[]>([]);
  const [newMsg, setNewMsg] = useState('');
  const [sending, setSending] = useState(false);
  const [loading, setLoading] = useState(true);
  const [users, setUsers] = useState<any[]>([]);
  const [showNewDM, setShowNewDM] = useState(false);
  const [mobileShowChat, setMobileShowChat] = useState(false);
  const [beaconTyping, setBeaconTyping] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const sseRef = useRef<EventSource | null>(null);
  const activeChannelRef = useRef<number | null>(null);

  // Keep ref in sync with active channel
  useEffect(() => {
    activeChannelRef.current = activeChannel?.id || null;
  }, [activeChannel]);

  // Load channels
  const loadChannels = useCallback(async () => {
    try {
      // Ensure office channel exists
      await axios.post(`${API}/api/chat/channels/ensure-office`, {}, { headers: headers() });
      const r = await axios.get(`${API}/api/chat/channels`, { headers: headers() });
      setChannels(r.data || []);
      return r.data || [];
    } catch (e) {
      console.error('Failed to load channels:', e);
      return [];
    }
  }, []);

  // Load messages for a channel
  const loadMessages = useCallback(async (channelId: number) => {
    try {
      const r = await axios.get(`${API}/api/chat/channels/${channelId}/messages?limit=100`, { headers: headers() });
      setMessages(r.data || []);
      // Mark as read
      axios.post(`${API}/api/chat/channels/${channelId}/read`, {}, { headers: headers() }).catch(() => {});
    } catch (e) {
      console.error('Failed to load messages:', e);
    }
  }, []);

  // Load users for DM
  const loadUsers = useCallback(async () => {
    try {
      const r = await axios.get(`${API}/api/chat/users`, { headers: headers() });
      setUsers(r.data || []);
    } catch {}
  }, []);

  // Init
  useEffect(() => {
    if (!user) return;
    (async () => {
      setLoading(true);
      const chs = await loadChannels();
      await loadUsers();
      // Ensure BEACON channel exists
      try { await axios.post(`${API}/api/chat/channels/ensure-beacon`, {}, { headers: headers() }); } catch {}
      // Re-load channels to pick up BEACON
      const updatedChs = await loadChannels();
      // Auto-select office channel
      const office = updatedChs.find((c: any) => c.channel_type === 'office');
      if (office) {
        setActiveChannel(office);
        await loadMessages(office.id);
      } else if (updatedChs.length > 0) {
        setActiveChannel(updatedChs[0]);
        await loadMessages(updatedChs[0].id);
      }
      setLoading(false);
    })();
  }, [user]);

  // SSE for live messages
  useEffect(() => {
    if (!user) return;
    let es: EventSource | null = null;
    try {
      es = new EventSource(`${API}/api/events/stream`);
      sseRef.current = es;

      es.addEventListener('chat:message', (event: MessageEvent) => {
        try {
          const parsed = JSON.parse(event.data);
          const data = parsed.data || parsed;
          const msg = data.message;
          const channelId = data.channel_id;

          // If this message is for the active channel, append it
          if (channelId === activeChannelRef.current && msg) {
            setMessages(prev => {
              // Avoid duplicates
              if (prev.find(m => m.id === msg.id)) return prev;
              return [...prev, msg];
            });
            // If BEACON just responded, clear typing indicator
            if (msg.sender_name === 'BEACON' || msg.sender_username === 'beacon.ai') {
              setBeaconTyping(false);
            }
            // Mark as read
            axios.post(`${API}/api/chat/channels/${channelId}/read`, {}, { headers: headers() }).catch(() => {});
          }

          // Refresh channel list (unread counts)
          loadChannels();
        } catch (e) {
          console.warn('SSE parse error:', e);
        }
      });

      es.onerror = () => {
        es?.close();
        // Reconnect after 5s
        setTimeout(() => {
          if (user) {
            // Will be re-established by effect cleanup+rerun
          }
        }, 5000);
      };
    } catch {}

    return () => {
      es?.close();
      sseRef.current = null;
    };
  }, [user, loadChannels]);

  // Auto-scroll to bottom on new messages
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  // Send message
  const handleSend = async () => {
    if (!newMsg.trim() || !activeChannel || sending) return;
    setSending(true);
    try {
      const form = new FormData();
      form.append('content', newMsg.trim());
      form.append('message_type', 'text');
      await axios.post(`${API}/api/chat/channels/${activeChannel.id}/messages`, form, {
        headers: { ...headers(), 'Content-Type': 'multipart/form-data' },
      });
      // Show typing indicator in BEACON channel
      if (activeChannel.channel_type === 'beacon') {
        setBeaconTyping(true);
        // Safety timeout — clear typing after 30s in case SSE misses the response
        setTimeout(() => setBeaconTyping(false), 30000);
      }
      setNewMsg('');
      inputRef.current?.focus();
    } catch (e) {
      console.error('Send failed:', e);
    }
    setSending(false);
  };

  // Start DM
  const startDM = async (userId: number) => {
    try {
      const r = await axios.post(`${API}/api/chat/channels/dm`, { user_id: userId }, { headers: headers() });
      const ch = r.data;
      setActiveChannel(ch);
      await loadMessages(ch.id);
      await loadChannels();
      setShowNewDM(false);
      setMobileShowChat(true);
    } catch (e) {
      console.error('DM creation failed:', e);
    }
  };

  // Select channel
  const selectChannel = async (ch: any) => {
    setActiveChannel(ch);
    await loadMessages(ch.id);
    setMobileShowChat(true);
  };

  // Render message content with URL detection, auto-embed images/GIFs, and clickable links
  const renderMessageContent = (content: string) => {
    const urlRegex = /(https?:\/\/[^\s<]+)/g;
    const imageExts = /\.(gif|png|jpg|jpeg|webp|svg)(\?.*)?$/i;
    const parts = content.split(urlRegex);
    
    return parts.map((part, i) => {
      if (urlRegex.test(part)) {
        // Reset lastIndex since we're reusing the regex
        urlRegex.lastIndex = 0;
        if (imageExts.test(part)) {
          // It's an image/GIF URL — embed it
          return (
            <div key={i} className="my-1.5">
              <img src={part} alt="" className="max-w-xs max-h-64 rounded-lg" loading="lazy"
                onError={(e) => {
                  // If image fails to load, fall back to link
                  const el = e.currentTarget;
                  const link = document.createElement('a');
                  link.href = part;
                  link.target = '_blank';
                  link.className = 'text-cyan-400 hover:underline text-sm break-all';
                  link.textContent = part;
                  el.parentElement?.replaceChild(link, el);
                }}
              />
            </div>
          );
        } else {
          // Regular URL — make it clickable
          return (
            <a key={i} href={part} target="_blank" rel="noopener noreferrer"
              className="text-cyan-400 hover:underline break-all">{part}</a>
          );
        }
      }
      // Plain text
      return part ? <span key={i}>{part}</span> : null;
    });
  };

  if (!user) return (
    <div className="min-h-screen">
      <div className="glass sticky top-0 z-50 border-b border-white/20 h-14" />
      <main className="max-w-[1600px] mx-auto px-4 sm:px-6 lg:px-8 py-6">
        <div className="h-8 w-56 rounded-lg bg-slate-200 animate-pulse mb-6" />
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-6">
          {[1,2,3,4].map(i => <div key={i} className="h-20 rounded-xl bg-slate-200 animate-pulse" />)}
        </div>
        <div className="h-96 rounded-xl bg-slate-200 animate-pulse" />
      </main>
    </div>
  );

  const officeChannels = channels.filter(c => c.channel_type === 'office');
  const beaconChannels = channels.filter(c => c.channel_type === 'beacon');
  const dmChannels = channels.filter(c => c.channel_type === 'dm');

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-950 via-slate-900 to-slate-950 text-white">
      <Navbar />
      <div className="flex" style={{ height: 'calc(100vh - 56px)' }}>
        {/* Sidebar — channel list */}
        <div className={`${mobileShowChat ? 'hidden md:flex' : 'flex'} flex-col w-full md:w-72 lg:w-80 border-r border-white/10 bg-slate-900/50`}>
          {/* Sidebar header */}
          <div className="p-4 border-b border-white/10 flex items-center justify-between">
            <h2 className="text-lg font-semibold flex items-center gap-2">
              <MessageCircle size={20} className="text-cyan-400" /> Chat
            </h2>
            <button
              onClick={() => setShowNewDM(!showNewDM)}
              className="p-2 rounded-lg hover:bg-white/10 transition text-cyan-400"
              title="New DM"
            >
              <Plus size={18} />
            </button>
          </div>

          {/* New DM selector */}
          {showNewDM && (
            <div className="p-3 border-b border-white/10 bg-slate-800/50">
              <p className="text-xs text-slate-400 mb-2 uppercase tracking-wider">Start a conversation</p>
              {users.map(u => (
                <button
                  key={u.id}
                  onClick={() => startDM(u.id)}
                  className="w-full flex items-center gap-3 p-2 rounded-lg hover:bg-white/10 transition text-left"
                >
                  <div className={`w-8 h-8 rounded-full bg-gradient-to-br ${avatarColor(u.id)} flex items-center justify-center text-xs font-bold`}>
                    {getInitials(u.full_name)}
                  </div>
                  <div>
                    <p className="text-sm font-medium">{u.full_name}</p>
                    <p className="text-xs text-slate-400">{u.role}</p>
                  </div>
                </button>
              ))}
            </div>
          )}

          {/* Channel list */}
          <div className="flex-1 overflow-y-auto">
            {/* Office channels */}
            {officeChannels.length > 0 && (
              <div className="p-3">
                <p className="text-xs text-slate-500 uppercase tracking-wider mb-2 px-2">Channels</p>
                {officeChannels.map(ch => (
                  <button
                    key={ch.id}
                    onClick={() => selectChannel(ch)}
                    className={`w-full flex items-center gap-3 p-2.5 rounded-lg transition text-left mb-0.5 ${
                      activeChannel?.id === ch.id
                        ? 'bg-cyan-500/20 text-cyan-300'
                        : 'hover:bg-white/5 text-slate-300'
                    }`}
                  >
                    <Hash size={18} className={activeChannel?.id === ch.id ? 'text-cyan-400' : 'text-slate-500'} />
                    <span className="flex-1 text-sm font-medium truncate">{ch.name}</span>
                    {ch.unread > 0 && (
                      <span className="bg-cyan-500 text-white text-xs font-bold px-2 py-0.5 rounded-full min-w-[20px] text-center">
                        {ch.unread}
                      </span>
                    )}
                  </button>
                ))}
              </div>
            )}

            {/* BEACON AI Channel */}
            {beaconChannels.length > 0 && (
              <div className="p-3">
                <p className="text-xs text-slate-500 uppercase tracking-wider mb-2 px-2">AI Assistant</p>
                {beaconChannels.map(ch => (
                  <button
                    key={ch.id}
                    onClick={() => selectChannel(ch)}
                    className={`w-full flex items-center gap-3 p-2.5 rounded-lg transition text-left mb-0.5 ${
                      activeChannel?.id === ch.id
                        ? 'bg-amber-500/20 text-amber-300'
                        : 'hover:bg-white/5 text-slate-300'
                    }`}
                  >
                    <div className={`w-5 h-5 rounded-full flex items-center justify-center ${
                      activeChannel?.id === ch.id ? 'bg-amber-400/30' : 'bg-amber-500/20'
                    }`}>
                      <Zap size={12} className={activeChannel?.id === ch.id ? 'text-amber-300' : 'text-amber-500'} />
                    </div>
                    <span className="flex-1 text-sm font-medium truncate">{ch.name}</span>
                    {ch.unread > 0 && (
                      <span className="bg-amber-500 text-white text-xs font-bold px-2 py-0.5 rounded-full min-w-[20px] text-center">
                        {ch.unread}
                      </span>
                    )}
                  </button>
                ))}
              </div>
            )}

            {/* DMs */}
            {dmChannels.length > 0 && (
              <div className="p-3">
                <p className="text-xs text-slate-500 uppercase tracking-wider mb-2 px-2">Direct Messages</p>
                {dmChannels.map(ch => (
                  <button
                    key={ch.id}
                    onClick={() => selectChannel(ch)}
                    className={`w-full flex items-center gap-3 p-2.5 rounded-lg transition text-left mb-0.5 ${
                      activeChannel?.id === ch.id
                        ? 'bg-cyan-500/20 text-cyan-300'
                        : 'hover:bg-white/5 text-slate-300'
                    }`}
                  >
                    <div className={`w-7 h-7 rounded-full bg-gradient-to-br ${avatarColor(ch.id)} flex items-center justify-center text-xs font-bold flex-shrink-0`}>
                      {getInitials(ch.name)}
                    </div>
                    <span className="flex-1 text-sm font-medium truncate">{ch.name}</span>
                    {ch.unread > 0 && (
                      <span className="bg-cyan-500 text-white text-xs font-bold px-2 py-0.5 rounded-full min-w-[20px] text-center">
                        {ch.unread}
                      </span>
                    )}
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* Main chat area */}
        <div className={`${!mobileShowChat ? 'hidden md:flex' : 'flex'} flex-1 flex-col`}>
          {activeChannel ? (
            <>
              {/* Chat header */}
              <div className="p-4 border-b border-white/10 bg-slate-900/30 flex items-center gap-3">
                <button
                  onClick={() => setMobileShowChat(false)}
                  className="md:hidden p-1.5 rounded-lg hover:bg-white/10 transition"
                >
                  <ArrowLeft size={18} />
                </button>
                {activeChannel.channel_type === 'office' ? (
                  <Hash size={20} className="text-cyan-400" />
                ) : activeChannel.channel_type === 'beacon' ? (
                  <div className="w-8 h-8 rounded-full bg-gradient-to-br from-amber-400 to-orange-500 flex items-center justify-center">
                    <Zap size={16} className="text-white" />
                  </div>
                ) : (
                  <div className={`w-8 h-8 rounded-full bg-gradient-to-br ${avatarColor(activeChannel.id)} flex items-center justify-center text-xs font-bold`}>
                    {getInitials(activeChannel.name)}
                  </div>
                )}
                <div>
                  <h3 className="font-semibold text-sm">{activeChannel.name}</h3>
                  <p className="text-xs text-slate-400">
                    {activeChannel.channel_type === 'beacon'
                      ? 'AI Insurance Knowledge Assistant — Ask anything'
                      : activeChannel.channel_type === 'office'
                      ? `${activeChannel.members?.length || 0} members`
                      : 'Direct Message'}
                  </p>
                </div>
              </div>

              {/* Messages */}
              <div className="flex-1 overflow-y-auto p-4 space-y-1">
                {messages.length === 0 && (
                  <div className="flex flex-col items-center justify-center h-full text-slate-500">
                    <MessageCircle size={48} className="mb-3 opacity-30" />
                    <p className="text-sm">No messages yet. Say hello!</p>
                  </div>
                )}
                {messages.map((msg, i) => {
                  const isMe = msg.sender_id === user?.id;
                  const isBeacon = msg.sender_name === 'BEACON' || msg.sender_username === 'beacon.ai';
                  const showAvatar = i === 0 || messages[i - 1]?.sender_id !== msg.sender_id ||
                    (new Date(msg.created_at).getTime() - new Date(messages[i - 1]?.created_at).getTime()) > 300000;
                  
                  return (
                    <div key={msg.id} className={`${showAvatar ? 'mt-4' : 'mt-0.5'}`}>
                      {showAvatar && (
                        <div className="flex items-center gap-2 mb-1">
                          {isBeacon ? (
                            <div className="w-7 h-7 rounded-full bg-gradient-to-br from-amber-400 to-orange-500 flex items-center justify-center flex-shrink-0">
                              <Zap size={14} className="text-white" />
                            </div>
                          ) : (
                            <div className={`w-7 h-7 rounded-full bg-gradient-to-br ${avatarColor(msg.sender_id)} flex items-center justify-center text-[10px] font-bold flex-shrink-0`}>
                              {getInitials(msg.sender_name || msg.sender_username)}
                            </div>
                          )}
                          <span className={`text-sm font-semibold ${isBeacon ? 'text-amber-300' : 'text-slate-200'}`}>
                            {msg.sender_name || msg.sender_username}
                          </span>
                          <span className="text-xs text-slate-500">{formatTime(msg.created_at)}</span>
                        </div>
                      )}
                      <div className={`pl-9 ${showAvatar ? '' : ''}`}>
                        {msg.message_type === 'file' && msg.file_path ? (
                          <div>
                            {msg.content && <p className="text-sm text-slate-200 mb-1">{msg.content}</p>}
                            <a
                              href={`${API}${msg.file_path}`}
                              target="_blank"
                              rel="noopener"
                              className="inline-flex items-center gap-2 px-3 py-2 rounded-lg bg-white/5 border border-white/10 hover:bg-white/10 transition text-sm"
                            >
                              <Paperclip size={14} className="text-cyan-400" />
                              <span className="text-cyan-300">{msg.file_name || 'Attachment'}</span>
                            </a>
                          </div>
                        ) : (
                          <div className={`text-sm leading-relaxed break-words ${isBeacon ? 'text-slate-200' : 'text-slate-200'}`}>
                            {isBeacon ? (
                              <div className="prose prose-invert prose-sm max-w-none"
                                dangerouslySetInnerHTML={{
                                  __html: (msg.content || '')
                                    .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
                                    .replace(/\*(.*?)\*/g, '<em>$1</em>')
                                    .replace(/^• /gm, '&bull; ')
                                    .replace(/^- /gm, '&bull; ')
                                    .replace(/\n/g, '<br />')
                                }}
                              />
                            ) : (
                              <div>{renderMessageContent(msg.content || '')}</div>
                            )}
                          </div>
                        )}
                        {/* Seen receipts for DMs and @mentions */}
                        {isMe && msg.seen_by && msg.seen_by.length > 0 && (
                          <div className="flex items-center gap-1 mt-0.5 text-[10px] text-slate-500">
                            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" className="text-cyan-500">
                              <polyline points="20 6 9 17 4 12" />
                            </svg>
                            <span>
                              Seen by {msg.seen_by.map((s: any) => s.name?.split(' ')[0] || 'someone').join(', ')}
                            </span>
                          </div>
                        )}
                      </div>
                    </div>
                  );
                })}
                {/* BEACON typing indicator */}
                {beaconTyping && activeChannel?.channel_type === 'beacon' && <BeaconTyping />}
                <div ref={messagesEndRef} />
              </div>

              {/* Input */}
              <div className="p-3 border-t border-white/10 bg-slate-900/30">
                <div className="flex items-center gap-2">
                  <input
                    ref={inputRef}
                    type="text"
                    value={newMsg}
                    onChange={e => setNewMsg(e.target.value)}
                    onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend(); } }}
                    placeholder={activeChannel.channel_type === 'beacon' ? 'Ask BEACON anything about insurance...' : `Message ${activeChannel.name}...`}
                    className="flex-1 bg-white/5 border border-white/10 rounded-xl px-4 py-2.5 text-sm text-white placeholder-slate-500 focus:outline-none focus:border-cyan-500/50 focus:ring-1 focus:ring-cyan-500/20"
                    autoComplete="off"
                  />
                  <button
                    onClick={handleSend}
                    disabled={!newMsg.trim() || sending}
                    className="p-2.5 rounded-xl bg-cyan-500 hover:bg-cyan-400 disabled:opacity-30 disabled:cursor-not-allowed transition text-white"
                  >
                    <Send size={18} />
                  </button>
                </div>
              </div>
            </>
          ) : (
            <div className="flex-1 flex items-center justify-center text-slate-500">
              <div className="text-center">
                <MessageCircle size={64} className="mx-auto mb-4 opacity-20" />
                <p className="text-lg font-medium">Select a conversation</p>
                <p className="text-sm mt-1">Choose a channel or start a DM</p>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
