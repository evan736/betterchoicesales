import React, { useState, useEffect, useRef, useCallback } from 'react';
import { chatAPI } from '../lib/api';
import { useAuth } from '../contexts/AuthContext';
import { useChat } from '../contexts/ChatContext';
import { useEmail } from '../contexts/EmailContext';
import {
  MessageCircle, X, Send, Paperclip, Smile, AtSign, Hash,
  Users, ChevronLeft, Image, FileText, Trash2, Edit3, Reply,
  Bell, Search, Loader2, Check, CheckCheck, PanelRightClose, PanelRightOpen,
  Mail,
} from 'lucide-react';

// Email toggle button used in collapsed sidebar
function EmailToggleButton() {
  const { sidebarOpen: emailOpen, toggleSidebar: toggleEmail, unreadCount } = useEmail();
  return (
    <button
      onClick={() => { toggleEmail(); }}
      className={`relative h-10 w-10 rounded-lg flex items-center justify-center transition-colors ${
        emailOpen ? 'bg-blue-500/30 text-blue-300' : 'bg-blue-500/15 text-blue-400 hover:bg-blue-500/25'
      }`}
      title={emailOpen ? "Close Email Inbox" : "Open Email Inbox"}
    >
      <Mail size={20} />
      {!emailOpen && unreadCount > 0 && (
        <span className="absolute -top-1 -right-1 h-4 min-w-[16px] px-1 rounded-full bg-red-500 text-white text-[9px] font-bold flex items-center justify-center animate-pulse">
          {unreadCount > 99 ? '99+' : unreadCount}
        </span>
      )}
    </button>
  );
}

// Popular emoji palette
const EMOJI_LIST = ['👍','👎','❤️','🎉','😂','🔥','👀','💯','✅','❌','🤔','👏','🙏','💪','🚀','⭐'];

// GIF search via Tenor
const TENOR_KEY = 'AIzaSyAyimkuYQYF_FXVALexPuGQctUWRURdCYQ'; // Free tier key

interface Message {
  id: number;
  channel_id: number;
  sender_id: number;
  sender_name: string;
  sender_username: string;
  content: string | null;
  message_type: string;
  file_name: string | null;
  file_path: string | null;
  file_type: string | null;
  file_size: number | null;
  mentions: number[];
  reactions: Record<string, number[]>;
  reply_to_id: number | null;
  is_edited: boolean;
  is_deleted: boolean;
  created_at: string;
}

interface Channel {
  id: number;
  channel_type: string;
  name: string;
  members: { user_id: number; username: string; full_name: string }[];
  unread: number;
}

interface ChatUser {
  id: number;
  username: string;
  full_name: string;
  role: string;
}

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'https://better-choice-api.onrender.com';

export default function ChatPanel() {
  const { user } = useAuth();
  const { sidebarOpen: open, toggleSidebar, openSidebar, closeSidebar } = useChat();
  const { sidebarOpen: emailOpen } = useEmail();
  const [channels, setChannels] = useState<Channel[]>([]);
  const [activeChannel, setActiveChannel] = useState<Channel | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [file, setFile] = useState<File | null>(null);
  const [loading, setLoading] = useState(false);
  const [sending, setSending] = useState(false);
  const [showEmoji, setShowEmoji] = useState(false);
  const [showGif, setShowGif] = useState(false);
  const [gifSearch, setGifSearch] = useState('');
  const [gifs, setGifs] = useState<any[]>([]);
  const [gifLoading, setGifLoading] = useState(false);
  const [chatUsers, setChatUsers] = useState<ChatUser[]>([]);
  const [showMentions, setShowMentions] = useState(false);
  const [mentionFilter, setMentionFilter] = useState('');
  const [totalUnread, setTotalUnread] = useState(0);
  const [totalMentions, setTotalMentions] = useState(0);
  const [unreadMap, setUnreadMap] = useState<Record<number, number>>({});
  const [showNewDM, setShowNewDM] = useState(false);
  const [replyTo, setReplyTo] = useState<Message | null>(null);
  const [view, setView] = useState<'channels' | 'chat'>('channels');
  const [chatSearch, setChatSearch] = useState('');
  const [chatSearchResults, setChatSearchResults] = useState<any[] | null>(null);
  const [chatSearching, setChatSearching] = useState(false);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const pollRef = useRef<any>(null);
  const notifAudio = useRef<HTMLAudioElement | null>(null);
  const prevUnreadRef = useRef<number>(0);

  // Initialize notification sound
  useEffect(() => {
    notifAudio.current = new Audio('/notification.wav');
    notifAudio.current.volume = 0.5;
  }, []);

  // Load channels + unread on mount
  useEffect(() => {
    if (!user) return;
    loadChannels();
    loadUnread();
    // Poll for new messages every 8 seconds
    pollRef.current = setInterval(() => {
      loadUnread();
      if (activeChannel) loadMessages(activeChannel.id, true);
    }, 4000);
    return () => clearInterval(pollRef.current);
  }, [user]);

  // Scroll to bottom on new messages
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const loadChannels = async () => {
    try {
      // Ensure office channel exists
      await chatAPI.ensureOffice();
      const res = await chatAPI.channels();
      setChannels(res.data);
      // Load users for mentions/DMs
      const uRes = await chatAPI.users();
      setChatUsers(uRes.data);
    } catch (e) {
      console.error('Failed to load channels:', e);
    }
  };

  const loadUnread = async () => {
    try {
      const res = await chatAPI.unread();
      const newTotal = res.data.total_unread;
      // Play notification sound when new unread messages arrive
      if (newTotal > prevUnreadRef.current && prevUnreadRef.current >= 0) {
        try { notifAudio.current?.play(); } catch {}
      }
      prevUnreadRef.current = newTotal;
      setTotalUnread(newTotal);
      setTotalMentions(res.data.total_mentions);
      const map: Record<number, number> = {};
      for (const ch of res.data.channels) {
        map[ch.channel_id] = ch.unread;
      }
      setUnreadMap(map);
    } catch (e) {
      // silently fail
    }
  };

  const loadMessages = async (channelId: number, silent = false) => {
    if (!silent) setLoading(true);
    try {
      const res = await chatAPI.messages(channelId);
      setMessages(res.data);
      if (!silent) {
        await chatAPI.markRead(channelId);
        loadUnread();
      }
    } catch (e) {
      console.error('Failed to load messages:', e);
    } finally {
      if (!silent) setLoading(false);
    }
  };

  const openChannel = async (ch: Channel) => {
    setActiveChannel(ch);
    setView('chat');
    await loadMessages(ch.id);
    await chatAPI.markRead(ch.id);
    loadUnread();
  };

  const startDM = async (userId: number) => {
    try {
      const res = await chatAPI.createDM(userId);
      const ch = res.data;
      setShowNewDM(false);
      await loadChannels();
      setActiveChannel(ch);
      setView('chat');
      await loadMessages(ch.id);
    } catch (e) {
      console.error('Failed to create DM:', e);
    }
  };

  const handleSend = async () => {
    if ((!input.trim() && !file) || sending) return;
    setSending(true);
    try {
      const fd = new FormData();
      if (input.trim()) fd.append('content', input.trim());
      if (file) fd.append('file', file);
      if (replyTo) fd.append('reply_to_id', String(replyTo.id));

      // Extract @mentions from input
      const mentionRegex = /@(\w+)/g;
      let match;
      const mentionIds: number[] = [];
      while ((match = mentionRegex.exec(input)) !== null) {
        const found = chatUsers.find(u =>
          u.username.toLowerCase() === match![1].toLowerCase() ||
          u.full_name.toLowerCase().includes(match![1].toLowerCase())
        );
        if (found) mentionIds.push(found.id);
      }
      if (mentionIds.length > 0) fd.append('mentions', mentionIds.join(','));

      await chatAPI.send(activeChannel!.id, fd);
      setInput('');
      setFile(null);
      setReplyTo(null);
      await loadMessages(activeChannel!.id);
    } catch (e) {
      console.error('Send failed:', e);
    } finally {
      setSending(false);
    }
  };

  const handleReact = async (msgId: number, emoji: string) => {
    try {
      await chatAPI.react(msgId, emoji);
      await loadMessages(activeChannel!.id, true);
    } catch (e) {
      console.error('React failed:', e);
    }
    setShowEmoji(false);
  };

  const handleDelete = async (msgId: number) => {
    if (!confirm('Delete this message?')) return;
    try {
      await chatAPI.deleteMsg(msgId);
      await loadMessages(activeChannel!.id, true);
    } catch (e) {
      console.error('Delete failed:', e);
    }
  };

  const handleChatSearch = async () => {
    if (!chatSearch.trim()) { setChatSearchResults(null); return; }
    setChatSearching(true);
    try {
      const res = await chatAPI.searchMessages(chatSearch.trim());
      setChatSearchResults(res.data.results);
    } catch (e) { console.error(e); }
    finally { setChatSearching(false); }
  };

  const clearChatSearch = () => {
    setChatSearch('');
    setChatSearchResults(null);
  };

  const searchGifs = async (query: string) => {
    if (!query.trim()) return;
    setGifLoading(true);
    try {
      const res = await fetch(
        `https://tenor.googleapis.com/v2/search?q=${encodeURIComponent(query)}&key=${TENOR_KEY}&limit=12&media_filter=tinygif`
      );
      const data = await res.json();
      setGifs(data.results || []);
    } catch (e) {
      console.error('GIF search failed:', e);
    } finally {
      setGifLoading(false);
    }
  };

  const sendGif = async (gifUrl: string) => {
    if (!activeChannel) return;
    const fd = new FormData();
    fd.append('content', gifUrl);
    fd.append('message_type', 'gif');
    try {
      await chatAPI.send(activeChannel.id, fd);
      setShowGif(false);
      setGifSearch('');
      setGifs([]);
      await loadMessages(activeChannel.id);
    } catch (e) {
      console.error('GIF send failed:', e);
    }
  };

  const insertMention = (u: ChatUser) => {
    setInput(prev => {
      const atIdx = prev.lastIndexOf('@');
      return prev.slice(0, atIdx) + `@${u.username} `;
    });
    setShowMentions(false);
    inputRef.current?.focus();
  };

  const handleInputChange = (val: string) => {
    setInput(val);
    // Detect @mention typing
    const atMatch = val.match(/@(\w*)$/);
    if (atMatch) {
      setMentionFilter(atMatch[1]);
      setShowMentions(true);
    } else {
      setShowMentions(false);
    }
  };

  const formatTime = (iso: string) => {
    const d = new Date(iso);
    const now = new Date();
    const isToday = d.toDateString() === now.toDateString();
    if (isToday) return d.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' });
    return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' });
  };

  const getInitials = (name: string) => {
    return name.split(' ').map(w => w[0]).join('').slice(0, 2).toUpperCase();
  };

  const initColor = (name: string) => {
    const colors = ['#06b6d4', '#8b5cf6', '#f59e0b', '#10b981', '#ef4444', '#ec4899', '#6366f1', '#14b8a6'];
    let hash = 0;
    for (let i = 0; i < name.length; i++) hash = name.charCodeAt(i) + ((hash << 5) - hash);
    return colors[Math.abs(hash) % colors.length];
  };

  if (!user) return null;

  // Collapsed sidebar bar — includes both Chat + Email icons
  // Always show this bar (it sits at right-0, behind any open panels)
  const collapsedBar = (
    <div className="fixed top-0 right-0 h-full w-12 z-30 bg-[#0a1628]/80 border-l border-cyan-900/20 flex flex-col items-center pt-20 gap-3"
      style={{ backdropFilter: 'blur(10px)' }}
    >
      {/* Email icon */}
      <EmailToggleButton />
      {/* Chat icon */}
      <button
        onClick={() => { if (open) { closeSidebar(); } else { openSidebar(); loadChannels(); loadUnread(); } }}
        className={`relative h-10 w-10 rounded-lg flex items-center justify-center transition-colors ${
          open ? 'bg-cyan-500/30 text-cyan-300' : 'bg-cyan-500/15 text-cyan-400 hover:bg-cyan-500/25'
        }`}
        title={open ? "Close Team Chat" : "Open Team Chat"}
      >
        <MessageCircle size={20} />
        {!open && totalUnread > 0 && (
          <span className="absolute -top-1 -right-1 h-4 min-w-[16px] px-1 rounded-full bg-red-500 text-white text-[9px] font-bold flex items-center justify-center animate-pulse">
            {totalUnread > 99 ? '99+' : totalUnread}
          </span>
        )}
      </button>
    </div>
  );

  if (!open) {
    return collapsedBar;
  }

  return (
    <>
      {collapsedBar}
      <div className="fixed top-0 h-full w-[380px] z-40 flex flex-col bg-[#0a1628] border-l border-cyan-900/30 shadow-2xl shadow-black/40"
        style={{ right: '48px', backdropFilter: 'blur(20px)' }}
      >
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 bg-gradient-to-r from-[#0d1f3c] to-[#0a1628] border-b border-cyan-900/20">
        {view === 'chat' && activeChannel ? (
          <>
            <button onClick={() => { setView('channels'); setActiveChannel(null); }} className="text-slate-400 hover:text-white mr-2">
              <ChevronLeft size={18} />
            </button>
            <div className="flex-1 min-w-0">
              <div className="text-sm font-semibold text-white truncate flex items-center gap-1.5">
                {activeChannel.channel_type === 'office' ? <Hash size={14} className="text-cyan-400" /> : <Users size={14} className="text-purple-400" />}
                {activeChannel.name}
              </div>
              <div className="text-[10px] text-slate-500">{activeChannel.members?.length || 0} members</div>
            </div>
          </>
        ) : (
          <div className="flex items-center gap-2">
            <MessageCircle size={18} className="text-cyan-400" />
            <span className="text-sm font-semibold text-white">Team Chat</span>
          </div>
        )}
        <button onClick={closeSidebar} className="text-slate-500 hover:text-white transition-colors">
          <PanelRightClose size={18} />
        </button>
      </div>

      {view === 'channels' ? (
        /* ── Channel List ── */
        <div className="flex-1 overflow-y-auto">
          {/* Search bar */}
          <div className="px-3 py-2 border-b border-white/[0.04]">
            <div className="flex items-center gap-1 bg-white/[0.04] rounded-lg px-2 py-1.5">
              <Search size={13} className="text-slate-500 flex-shrink-0" />
              <input
                value={chatSearch}
                onChange={e => { setChatSearch(e.target.value); if (!e.target.value) clearChatSearch(); }}
                onKeyDown={e => e.key === 'Enter' && handleChatSearch()}
                placeholder="Search messages..."
                className="flex-1 bg-transparent text-xs text-slate-200 placeholder:text-slate-600 outline-none"
              />
              {chatSearch && (
                <button onClick={clearChatSearch} className="text-slate-500 hover:text-slate-300 text-xs">✕</button>
              )}
            </div>
          </div>

          {/* Search Results */}
          {chatSearchResults ? (
            <div>
              <div className="px-3 py-1.5 text-[10px] text-cyan-400 font-semibold">
                {chatSearching ? 'Searching...' : `${chatSearchResults.length} result${chatSearchResults.length !== 1 ? 's' : ''} for "${chatSearch}"`}
              </div>
              {chatSearchResults.map((msg: any) => (
                <div key={msg.id} className="px-3 py-2 border-b border-white/[0.03] hover:bg-white/[0.03]">
                  <div className="flex items-center gap-1.5 mb-0.5">
                    <div className="h-5 w-5 rounded-full flex items-center justify-center text-[8px] font-bold text-white" style={{ background: initColor(msg.sender_name) }}>
                      {getInitials(msg.sender_name)}
                    </div>
                    <span className="text-[11px] font-medium text-slate-300">{msg.sender_name}</span>
                    <span className="text-[9px] text-slate-600 ml-auto">{msg.channel_name}</span>
                  </div>
                  <p className="text-[11px] text-slate-400 ml-6 truncate">{msg.content}</p>
                  <span className="text-[9px] text-slate-600 ml-6">
                    {new Date(msg.created_at).toLocaleDateString('en-US', { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })}
                  </span>
                </div>
              ))}
              {chatSearchResults.length === 0 && !chatSearching && (
                <div className="px-3 py-6 text-center text-xs text-slate-500">No messages found</div>
              )}
            </div>
          ) : (
          <>
          {/* Office Chat */}
          {channels.filter(c => c.channel_type === 'office').map(ch => (
            <button
              key={ch.id}
              onClick={() => openChannel(ch)}
              className="w-full flex items-center gap-3 px-4 py-3 hover:bg-white/[0.03] transition-colors border-b border-white/[0.03] text-left"
            >
              <div className="h-9 w-9 rounded-lg bg-cyan-500/15 flex items-center justify-center flex-shrink-0">
                <Hash size={16} className="text-cyan-400" />
              </div>
              <div className="flex-1 min-w-0">
                <div className="text-sm font-medium text-slate-200">{ch.name}</div>
                <div className="text-[10px] text-slate-500">{ch.members?.length} members</div>
              </div>
              {(unreadMap[ch.id] || 0) > 0 && (
                <span className="h-5 min-w-[20px] px-1.5 rounded-full bg-cyan-500 text-white text-[10px] font-bold flex items-center justify-center">
                  {unreadMap[ch.id]}
                </span>
              )}
            </button>
          ))}

          {/* DM Header */}
          <div className="flex items-center justify-between px-4 py-2 mt-1">
            <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">Direct Messages</span>
            <button onClick={() => setShowNewDM(!showNewDM)} className="text-cyan-400 hover:text-cyan-300 text-xs font-bold">+ New</button>
          </div>

          {/* New DM User Picker */}
          {showNewDM && (
            <div className="mx-3 mb-2 bg-white/[0.03] rounded-lg border border-white/[0.06] p-2 max-h-40 overflow-y-auto">
              {chatUsers.map(u => (
                <button
                  key={u.id}
                  onClick={() => startDM(u.id)}
                  className="w-full flex items-center gap-2 px-2 py-1.5 rounded hover:bg-white/[0.05] text-left"
                >
                  <div className="h-6 w-6 rounded-full flex items-center justify-center text-[9px] font-bold text-white" style={{ background: initColor(u.full_name) }}>
                    {getInitials(u.full_name)}
                  </div>
                  <span className="text-xs text-slate-300">{u.full_name}</span>
                  <span className="text-[10px] text-slate-600 ml-auto">{u.role}</span>
                </button>
              ))}
            </div>
          )}

          {/* DM Channels */}
          {channels.filter(c => c.channel_type === 'dm').map(ch => {
            const other = ch.members?.find(m => m.user_id !== (user as any)?.id);
            return (
              <button
                key={ch.id}
                onClick={() => openChannel(ch)}
                className="w-full flex items-center gap-3 px-4 py-2.5 hover:bg-white/[0.03] transition-colors text-left"
              >
                <div className="h-8 w-8 rounded-full flex items-center justify-center text-[10px] font-bold text-white flex-shrink-0"
                  style={{ background: initColor(other?.full_name || 'DM') }}>
                  {getInitials(other?.full_name || 'DM')}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="text-sm text-slate-300 truncate">{other?.full_name || ch.name}</div>
                </div>
                {(unreadMap[ch.id] || 0) > 0 && (
                  <span className="h-5 min-w-[20px] px-1.5 rounded-full bg-purple-500 text-white text-[10px] font-bold flex items-center justify-center">
                    {unreadMap[ch.id]}
                  </span>
                )}
              </button>
            );
          })}
          </>
          )}
        </div>
      ) : (
        /* ── Messages View ── */
        <>
          <div className="flex-1 overflow-y-auto px-3 py-2 space-y-1" style={{ scrollbarWidth: 'thin', scrollbarColor: '#1e293b transparent' }}>
            {loading ? (
              <div className="flex items-center justify-center h-full">
                <Loader2 size={24} className="animate-spin text-cyan-400" />
              </div>
            ) : messages.length === 0 ? (
              <div className="flex items-center justify-center h-full text-slate-600 text-xs">
                No messages yet. Say hello! 👋
              </div>
            ) : (
              messages.map((msg, i) => {
                const isMe = msg.sender_id === (user as any)?.id;
                const showAvatar = i === 0 || messages[i - 1]?.sender_id !== msg.sender_id;
                const isGif = msg.message_type === 'gif';

                return (
                  <div key={msg.id} className={`group ${showAvatar ? 'mt-3' : 'mt-0.5'}`}>
                    {/* Sender info */}
                    {showAvatar && (
                      <div className="flex items-center gap-2 mb-0.5">
                        <div className="h-6 w-6 rounded-full flex items-center justify-center text-[8px] font-bold text-white flex-shrink-0"
                          style={{ background: initColor(msg.sender_name) }}>
                          {getInitials(msg.sender_name)}
                        </div>
                        <span className="text-xs font-semibold text-slate-300">{isMe ? 'You' : msg.sender_name}</span>
                        <span className="text-[10px] text-slate-600">{formatTime(msg.created_at)}</span>
                      </div>
                    )}

                    {/* Reply reference */}
                    {msg.reply_to_id && (
                      <div className="ml-8 mb-0.5 px-2 py-1 rounded bg-white/[0.02] border-l-2 border-cyan-800 text-[10px] text-slate-500 truncate">
                        ↩ Reply
                      </div>
                    )}

                    {/* Message bubble */}
                    <div className={`ml-8 relative ${isGif ? '' : `rounded-lg px-3 py-1.5 text-sm max-w-[85%] ${
                      isMe ? 'bg-cyan-600/20 text-cyan-100' : 'bg-white/[0.04] text-slate-300'
                    }`}`}>
                      {/* Content */}
                      {isGif ? (
                        <img src={msg.content || ''} alt="GIF" className="rounded-lg max-w-[200px] max-h-[150px]" loading="lazy" />
                      ) : msg.content ? (
                        <span className="break-words whitespace-pre-wrap"
                          dangerouslySetInnerHTML={{
                            __html: msg.content.replace(
                              /@(\w+)/g,
                              '<span class="text-cyan-400 font-semibold">@$1</span>'
                            )
                          }}
                        />
                      ) : null}

                      {/* File attachment */}
                      {msg.file_path && (
                        <a
                          href={`${API_BASE}${msg.file_path}`}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="flex items-center gap-2 mt-1 px-2 py-1.5 rounded bg-white/[0.04] hover:bg-white/[0.08] transition-colors border border-white/[0.06]"
                        >
                          {msg.file_type && ['jpg', 'jpeg', 'png', 'gif', 'webp'].includes(msg.file_type) ? (
                            <Image size={14} className="text-green-400" />
                          ) : (
                            <FileText size={14} className="text-amber-400" />
                          )}
                          <span className="text-xs text-slate-300 truncate">{msg.file_name}</span>
                          <span className="text-[10px] text-slate-600 ml-auto">{msg.file_size ? `${(msg.file_size / 1024).toFixed(0)}KB` : ''}</span>
                        </a>
                      )}

                      {msg.is_edited && <span className="text-[9px] text-slate-600 ml-1">(edited)</span>}

                      {/* Hover actions */}
                      <div className="absolute -top-3 right-0 hidden group-hover:flex items-center gap-0.5 bg-[#0d1f3c] border border-white/[0.08] rounded-lg px-1 py-0.5 shadow-lg">
                        {EMOJI_LIST.slice(0, 4).map(e => (
                          <button key={e} onClick={() => handleReact(msg.id, e)} className="hover:scale-125 transition-transform text-xs p-0.5">{e}</button>
                        ))}
                        <button onClick={() => { setReplyTo(msg); inputRef.current?.focus(); }} className="p-0.5 text-slate-500 hover:text-white"><Reply size={12} /></button>
                        {isMe && (
                          <button onClick={() => handleDelete(msg.id)} className="p-0.5 text-slate-500 hover:text-red-400"><Trash2 size={12} /></button>
                        )}
                      </div>
                    </div>

                    {/* Reactions */}
                    {msg.reactions && Object.keys(msg.reactions).length > 0 && (
                      <div className="ml-8 flex flex-wrap gap-1 mt-0.5">
                        {Object.entries(msg.reactions).map(([emoji, userIds]) => (
                          <button
                            key={emoji}
                            onClick={() => handleReact(msg.id, emoji)}
                            className={`text-xs px-1.5 py-0.5 rounded-full border transition-colors ${
                              (userIds as number[]).includes((user as any)?.id)
                                ? 'bg-cyan-500/20 border-cyan-500/40 text-cyan-300'
                                : 'bg-white/[0.03] border-white/[0.06] text-slate-400 hover:bg-white/[0.06]'
                            }`}
                          >
                            {emoji} {(userIds as number[]).length}
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                );
              })
            )}
            <div ref={messagesEndRef} />
          </div>

          {/* Reply bar */}
          {replyTo && (
            <div className="px-3 py-1.5 bg-white/[0.02] border-t border-white/[0.04] flex items-center gap-2">
              <Reply size={12} className="text-cyan-400" />
              <span className="text-[10px] text-slate-400 truncate flex-1">Replying to {replyTo.sender_name}: {replyTo.content?.slice(0, 40)}</span>
              <button onClick={() => setReplyTo(null)} className="text-slate-600 hover:text-white"><X size={12} /></button>
            </div>
          )}

          {/* File preview */}
          {file && (
            <div className="px-3 py-1.5 bg-white/[0.02] border-t border-white/[0.04] flex items-center gap-2">
              <FileText size={12} className="text-amber-400" />
              <span className="text-[10px] text-slate-300 truncate flex-1">{file.name}</span>
              <button onClick={() => setFile(null)} className="text-slate-600 hover:text-white"><X size={12} /></button>
            </div>
          )}

          {/* @mention picker */}
          {showMentions && (
            <div className="absolute bottom-14 left-3 right-3 bg-[#0d1f3c] border border-white/[0.08] rounded-lg shadow-xl max-h-32 overflow-y-auto z-10">
              {chatUsers.filter(u =>
                !mentionFilter || u.full_name.toLowerCase().includes(mentionFilter.toLowerCase()) || u.username.toLowerCase().includes(mentionFilter.toLowerCase())
              ).map(u => (
                <button
                  key={u.id}
                  onClick={() => insertMention(u)}
                  className="w-full flex items-center gap-2 px-3 py-2 hover:bg-white/[0.05] text-left"
                >
                  <div className="h-5 w-5 rounded-full flex items-center justify-center text-[8px] font-bold text-white" style={{ background: initColor(u.full_name) }}>
                    {getInitials(u.full_name)}
                  </div>
                  <span className="text-xs text-slate-300">{u.full_name}</span>
                  <span className="text-[10px] text-slate-600">@{u.username}</span>
                </button>
              ))}
            </div>
          )}

          {/* Emoji picker */}
          {showEmoji && (
            <div className="absolute bottom-14 left-3 right-3 bg-[#0d1f3c] border border-white/[0.08] rounded-lg shadow-xl p-2 z-10">
              <div className="grid grid-cols-8 gap-1">
                {EMOJI_LIST.map(e => (
                  <button key={e} onClick={() => { setInput(prev => prev + e); setShowEmoji(false); inputRef.current?.focus(); }}
                    className="text-lg h-8 w-8 rounded hover:bg-white/[0.08] flex items-center justify-center transition-colors">
                    {e}
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* GIF picker */}
          {showGif && (
            <div className="absolute bottom-14 left-3 right-3 bg-[#0d1f3c] border border-white/[0.08] rounded-lg shadow-xl p-2 z-10 max-h-64 overflow-hidden flex flex-col">
              <div className="flex items-center gap-1 mb-2">
                <input
                  value={gifSearch}
                  onChange={e => setGifSearch(e.target.value)}
                  onKeyDown={e => e.key === 'Enter' && searchGifs(gifSearch)}
                  placeholder="Search GIFs..."
                  className="flex-1 bg-white/[0.05] border border-white/[0.08] rounded px-2 py-1 text-xs text-white placeholder-slate-600 outline-none focus:border-cyan-500/50"
                />
                <button onClick={() => searchGifs(gifSearch)} className="text-cyan-400 hover:text-cyan-300 p-1"><Search size={14} /></button>
              </div>
              <div className="overflow-y-auto grid grid-cols-3 gap-1">
                {gifLoading && <div className="col-span-3 flex justify-center py-4"><Loader2 size={20} className="animate-spin text-cyan-400" /></div>}
                {gifs.map((g, i) => (
                  <button key={i} onClick={() => sendGif(g.media_formats?.tinygif?.url || g.media_formats?.gif?.url)}
                    className="rounded overflow-hidden hover:opacity-80 transition-opacity">
                    <img src={g.media_formats?.tinygif?.url} alt="" className="w-full h-20 object-cover" loading="lazy" />
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* Input bar */}
          <div className="px-3 py-2 border-t border-white/[0.06] bg-[#0a1628]">
            <div className="flex items-center gap-1.5">
              <input type="file" ref={fileInputRef} className="hidden" onChange={e => { if (e.target.files?.[0]) setFile(e.target.files[0]); }} />
              <button onClick={() => fileInputRef.current?.click()} className="text-slate-500 hover:text-white p-1 transition-colors" title="Attach file">
                <Paperclip size={16} />
              </button>
              <button onClick={() => { setShowGif(!showGif); setShowEmoji(false); }} className="text-slate-500 hover:text-white p-1 transition-colors" title="GIFs">
                <Image size={16} />
              </button>
              <button onClick={() => { setShowEmoji(!showEmoji); setShowGif(false); }} className="text-slate-500 hover:text-white p-1 transition-colors" title="Emoji">
                <Smile size={16} />
              </button>
              <input
                ref={inputRef}
                value={input}
                onChange={e => handleInputChange(e.target.value)}
                onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend(); } }}
                placeholder="Type a message... (@mention)"
                className="flex-1 bg-white/[0.04] border border-white/[0.08] rounded-lg px-3 py-1.5 text-sm text-white placeholder-slate-600 outline-none focus:border-cyan-500/40 transition-colors"
              />
              <button
                onClick={handleSend}
                disabled={sending || (!input.trim() && !file)}
                className="text-cyan-400 hover:text-cyan-300 disabled:text-slate-700 p-1.5 transition-colors"
              >
                {sending ? <Loader2 size={16} className="animate-spin" /> : <Send size={16} />}
              </button>
            </div>
          </div>
        </>
      )}
    </div>
    </>
  );
}
