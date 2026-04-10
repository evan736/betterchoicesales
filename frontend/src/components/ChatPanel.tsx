import React, { useState, useEffect, useRef, useCallback } from 'react';
import { chatAPI } from '../lib/api';
import { useAuth } from '../contexts/AuthContext';
import { useChat } from '../contexts/ChatContext';
import { useEmail } from '../contexts/EmailContext';
import {
  MessageCircle, X, Send, Paperclip, Smile, AtSign, Hash,
  Users, ChevronLeft, ChevronRight, Image, FileText, Trash2, Edit3, Reply,
  Bell, BellOff, Search, Loader2, Check, CheckCheck, PanelRightClose, PanelRightOpen,
  Mail, Zap, Minimize2, Maximize2, ExternalLink,
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
  seen_by?: { user_id: number; name: string; read_at: string }[];
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
  const [inlineSearch, setInlineSearch] = useState('');
  const [inlineSearchOpen, setInlineSearchOpen] = useState(false);
  const [inlineMatchIds, setInlineMatchIds] = useState<number[]>([]);
  const [inlineMatchIdx, setInlineMatchIdx] = useState(0);
  const [beaconTyping, setBeaconTyping] = useState(false);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const messagesContainerRef = useRef<HTMLDivElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const pollRef = useRef<any>(null);
  const notifAudio = useRef<HTMLAudioElement | null>(null);
  const mentionAudio = useRef<HTMLAudioElement | null>(null);
  const prevUnreadRef = useRef<number>(0);
  const prevMentionsRef = useRef<number>(0);
  const activeChannelRef = useRef<Channel | null>(null);
  const [compact, setCompact] = useState(false);
  const [soundEnabled, setSoundEnabled] = useState(() => {
    if (typeof window !== 'undefined') {
      return localStorage.getItem('orbit-chat-sound') !== 'off';
    }
    return true;
  });

  const toggleSound = () => {
    const next = !soundEnabled;
    setSoundEnabled(next);
    soundEnabledRef.current = next;
    localStorage.setItem('orbit-chat-sound', next ? 'on' : 'off');
  };

  const soundEnabledRef = useRef(typeof window !== 'undefined' ? localStorage.getItem('orbit-chat-sound') !== 'off' : true);
  useEffect(() => { soundEnabledRef.current = soundEnabled; }, [soundEnabled]);

  // Keep ref in sync
  useEffect(() => { activeChannelRef.current = activeChannel; }, [activeChannel]);

  // Initialize notification sounds
  useEffect(() => {
    notifAudio.current = new Audio('/notification.wav');
    notifAudio.current.volume = 0.5;
    mentionAudio.current = new Audio('/notification.wav');
    mentionAudio.current.volume = 1.0;
    mentionAudio.current.playbackRate = 1.0;
  }, []);

  // Load channels + unread on mount
  useEffect(() => {
    if (!user) return;
    loadChannels();
    loadUnread();

    // Poll for new messages — direct fetch to avoid stale closures
    pollRef.current = setInterval(async () => {
      loadUnread();
      const ch = activeChannelRef.current;
      if (!ch) return;
      try {
        const res = await chatAPI.messages(ch.id);
        const freshMsgs = res.data || [];

        setMessages(prev => {
          // Only update if message count changed (avoid unnecessary rerenders)
          if (freshMsgs.length !== prev.length || 
              (freshMsgs.length > 0 && prev.length > 0 && freshMsgs[freshMsgs.length - 1]?.id !== prev[prev.length - 1]?.id)) {
            // Check for new BEACON message to clear typing
            if (ch.channel_type === 'beacon') {
              const prevIds = new Set(prev.map((m: any) => m.id));
              const hasNewBeacon = freshMsgs.some((m: any) =>
                !prevIds.has(m.id) && (m.sender_username === 'beacon.ai' || m.sender_name === 'BEACON')
              );
              if (hasNewBeacon) setBeaconTyping(false);
            }
            return freshMsgs;
          }
          return prev;
        });
      } catch {}
    }, 3000);

    // SSE for live chat messages with auto-reconnect
    let es: EventSource | null = null;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    
    const connectSSE = () => {
      try {
        es = new EventSource(`${API_BASE}/api/events/stream`);
        es.addEventListener('chat:message', (event: MessageEvent) => {
          try {
            const parsed = JSON.parse(event.data);
            const data = parsed.data || parsed;
            const msg = data.message;
            const channelId = data.channel_id;
            // If this is the active channel, append the message
            if (channelId === activeChannelRef.current?.id && msg) {
              setMessages(prev => {
                if (prev.find(m => m.id === msg.id)) return prev;
                return [...prev, msg];
              });
              // Mark as read immediately since user is viewing this channel
              chatAPI.markRead(channelId).catch(() => {});
              // Clear BEACON typing when bot responds
              if (msg.sender_username === 'beacon.ai' || msg.sender_name === 'BEACON') {
                setBeaconTyping(false);
              }
            }
            // Play loud mention ding if user was @mentioned
            const currentUsername = user?.username?.toLowerCase() || '';
            const currentName = user?.full_name?.toLowerCase() || '';
            const msgContent = (msg?.content || '').toLowerCase();
            const isMentioned = msgContent.includes(`@${currentUsername}`) || 
                               (currentName && msgContent.includes(`@${currentName.split(' ')[0]}`)) ||
                               (msg?.mentions && msg.mentions.some((m: any) => m.id === user?.id || m.user_id === user?.id));
            if (isMentioned && msg?.sender_id !== user?.id) {
              // Play mention sound 3 times rapidly — ALWAYS plays even if muted
              try {
                const playMention = () => {
                  const a = new Audio('/notification.wav');
                  a.volume = 1.0;
                  a.play().catch(() => {});
                };
                playMention();
                setTimeout(playMention, 300);
                setTimeout(playMention, 600);
              } catch {}
            }
            // Refresh unread counts
            loadUnread();
          } catch {}
        });
        es.onerror = () => {
          es?.close();
          es = null;
          reconnectTimer = setTimeout(connectSSE, 5000);
        };
      } catch {}
    };
    connectSSE();

    return () => { 
      clearInterval(pollRef.current); 
      es?.close(); 
      if (reconnectTimer) clearTimeout(reconnectTimer);
    };
  }, [user]);

  const justSentRef = useRef(false);
  const userScrolledUpRef = useRef(false);
  const prevMessageCountRef = useRef(0);

  // Scroll the messages container to the very bottom
  const scrollToBottom = () => {
    const el = messagesContainerRef.current;
    if (el) {
      el.scrollTop = el.scrollHeight + 9999;
    }
  };

  // Track if user has scrolled away from bottom
  const handleContainerScroll = () => {
    const el = messagesContainerRef.current;
    if (!el) return;
    const distFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
    userScrolledUpRef.current = distFromBottom > 200;
  };

  // After messages change, scroll to bottom unless user deliberately scrolled up
  useEffect(() => {
    if (messages.length === 0) return;

    const isNewMessages = messages.length !== prevMessageCountRef.current;
    prevMessageCountRef.current = messages.length;

    // Always scroll on: send, channel open, or new messages arriving while at bottom
    if (justSentRef.current || !userScrolledUpRef.current) {
      justSentRef.current = false;
      scrollToBottom();
      requestAnimationFrame(scrollToBottom);
      setTimeout(scrollToBottom, 100);
      setTimeout(scrollToBottom, 300);
    }
  }, [messages]);

  const loadChannels = async () => {
    try {
      // Ensure office + BEACON channels exist
      await chatAPI.ensureOffice();
      try { 
        const token = localStorage.getItem('token');
        await fetch(`${API_BASE}/api/chat/channels/ensure-beacon`, {
          method: 'POST',
          headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
          body: '{}',
        });
      } catch {}
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
      const newMentions = res.data.total_mentions || 0;
      // Play loud mention ding when new mentions arrive — ALWAYS plays even if muted
      if (newMentions > (prevMentionsRef.current || 0)) {
        try {
          const playMention = () => {
            const a = new Audio('/notification.wav');
            a.volume = 1.0;
            a.play().catch(() => {});
          };
          playMention();
          setTimeout(playMention, 300);
          setTimeout(playMention, 600);
        } catch {}
      } else if (newTotal > prevUnreadRef.current && prevUnreadRef.current >= 0) {
        // Regular notification sound for non-mention messages
        if (soundEnabledRef.current) try { notifAudio.current?.play(); } catch {}
      }
      prevUnreadRef.current = newTotal;
      prevMentionsRef.current = newMentions;
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
      const msgs = res.data || [];
      setMessages(msgs);
      // Always mark as read when viewing a channel
      await chatAPI.markRead(channelId);
      if (!silent) loadUnread();
    } catch (e) {
      console.error('Failed to load messages:', e);
    } finally {
      if (!silent) setLoading(false);
    }
  };

  const openChannel = async (ch: Channel) => {
    setActiveChannel(ch);
    setView('chat');
    userScrolledUpRef.current = false; // Reset scroll state on channel open
    // Immediately clear the unread badge for this channel (optimistic)
    setUnreadMap(prev => ({ ...prev, [ch.id]: 0 }));

    // BEACON: auto-clear if last message is >10 min old (conversation ended)
    if (ch.channel_type === 'beacon') {
      try {
        const res = await chatAPI.messages(ch.id);
        const msgs = res.data || [];
        // Find last non-welcome message
        const nonWelcome = msgs.filter((m: any) => msgs.indexOf(m) > 0);
        if (nonWelcome.length > 0) {
          const lastMsg = nonWelcome[nonWelcome.length - 1];
          const lastTs = new Date(lastMsg.created_at).getTime();
          const idleMs = Date.now() - lastTs;
          if (idleMs > 10 * 60 * 1000) {
            // Conversation ended — clear history on backend
            try {
              const token = localStorage.getItem('token');
              await fetch(`${API_BASE}/api/chat/channels/beacon/clear`, {
                method: 'POST',
                headers: { Authorization: `Bearer ${token}` },
              });
            } catch {}
          }
        }
      } catch {}
    }

    await loadMessages(ch.id);
    await chatAPI.markRead(ch.id);
    // Small delay to ensure server has processed the markRead before we fetch counts
    setTimeout(() => loadUnread(), 300);
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

  const handlePaste = (e: React.ClipboardEvent) => {
    const items = e.clipboardData?.items;
    if (!items) return;
    for (let i = 0; i < items.length; i++) {
      if (items[i].type.startsWith('image/')) {
        e.preventDefault();
        const blob = items[i].getAsFile();
        if (blob) {
          const ext = items[i].type.split('/')[1] || 'png';
          const named = new File([blob], `pasted-image.${ext}`, { type: items[i].type });
          setFile(named);
        }
        return;
      }
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

      const res = await chatAPI.send(activeChannel!.id, fd);
      setInput('');
      setFile(null);
      setReplyTo(null);
      justSentRef.current = true;
      // Show BEACON typing if in BEACON channel
      if (activeChannel?.channel_type === 'beacon') {
        setBeaconTyping(true);
        setTimeout(() => setBeaconTyping(false), 30000); // safety timeout
      }
      // Optimistically append the sent message so we don't need a full reload
      // The poll will reconcile with server state in 3 seconds
      const sentMsg = res?.data;
      if (sentMsg && sentMsg.id) {
        setMessages(prev => prev.find(m => m.id === sentMsg.id) ? prev : [...prev, sentMsg]);
      } else {
        // Fallback: reload messages if we didn't get the sent message back
        await loadMessages(activeChannel!.id);
      }
      // Scroll after a tick
      setTimeout(scrollToBottom, 50);
      setTimeout(scrollToBottom, 200);
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

  // Inline search within current chat
  const doInlineSearch = (term: string) => {
    setInlineSearch(term);
    if (!term.trim()) {
      setInlineMatchIds([]);
      setInlineMatchIdx(0);
      return;
    }
    const lower = term.toLowerCase();
    const matches = messages
      .filter(m => (m.content || '').toLowerCase().includes(lower))
      .map(m => m.id);
    setInlineMatchIds(matches);
    setInlineMatchIdx(0);
    // Scroll to first match
    if (matches.length > 0) {
      const el = document.getElementById(`msg-${matches[0]}`);
      if (el) el.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
  };

  const inlineSearchNav = (dir: 1 | -1) => {
    if (inlineMatchIds.length === 0) return;
    const next = (inlineMatchIdx + dir + inlineMatchIds.length) % inlineMatchIds.length;
    setInlineMatchIdx(next);
    const el = document.getElementById(`msg-${inlineMatchIds[next]}`);
    if (el) {
      el.scrollIntoView({ behavior: 'smooth', block: 'center' });
      el.classList.add('ring-1', 'ring-yellow-400/60');
      setTimeout(() => el.classList.remove('ring-1', 'ring-yellow-400/60'), 1500);
    }
  };

  const closeInlineSearch = () => {
    setInlineSearchOpen(false);
    setInlineSearch('');
    setInlineMatchIds([]);
    setInlineMatchIdx(0);
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
    <div className="fixed top-0 right-0 h-full w-12 z-20 bg-[#0a1628]/80 border-l border-cyan-900/20 flex flex-col items-center pt-20 gap-3"
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
      {/* BEACON AI icon */}
      <button
        onClick={() => {
          const beaconCh = channels.find(c => c.channel_type === 'beacon' && c.name !== 'BEACON');
          if (beaconCh) {
            openSidebar();
            openChannel(beaconCh);
          } else {
            openSidebar();
            loadChannels();
          }
        }}
        className={`relative h-10 w-10 rounded-lg flex items-center justify-center transition-colors ${
          activeChannel?.channel_type === 'beacon' && open
            ? 'bg-amber-500/30 text-amber-300'
            : 'bg-amber-500/15 text-amber-400 hover:bg-amber-500/25'
        }`}
        title="BEACON AI Assistant"
      >
        <Zap size={20} />
      </button>
    </div>
  );

  if (!open) {
    return collapsedBar;
  }

  const handlePopOut = () => {
    const w = compact ? 360 : 440;
    const popout = window.open(
      `${window.location.origin}/chat`,
      'orbit-chat',
      `width=${w},height=720,resizable=yes,scrollbars=no,toolbar=no,menubar=no,location=no`
    );
    if (popout) closeSidebar();
  };

  return (
    <>
      {collapsedBar}
      <div className={`fixed top-0 h-full z-30 flex flex-col bg-[#0a1628] border-l border-cyan-900/30 shadow-2xl shadow-black/40 transition-all duration-200 ${compact ? 'w-[300px]' : 'w-[380px]'}`}
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
                {activeChannel.channel_type === 'beacon' ? (
                  <Zap size={14} className="text-amber-400" />
                ) : activeChannel.channel_type === 'office' ? (
                  <Hash size={14} className="text-cyan-400" />
                ) : (
                  <Users size={14} className="text-purple-400" />
                )}
                {activeChannel.channel_type === 'beacon' ? 'BEACON' : activeChannel.name}
              </div>
              <div className="text-[10px] text-slate-500">
                {activeChannel.channel_type === 'beacon'
                  ? 'AI Insurance Expert — Ask anything'
                  : `${activeChannel.members?.length || 0} members`}
              </div>
            </div>
          </>
        ) : (
          <div className="flex items-center gap-2">
            <MessageCircle size={18} className="text-cyan-400" />
            <span className="text-sm font-semibold text-white">Team Chat</span>
          </div>
        )}
        <div className="flex items-center gap-1">
          {view === 'chat' && activeChannel && (
            <button onClick={() => { setInlineSearchOpen(!inlineSearchOpen); if (inlineSearchOpen) closeInlineSearch(); }}
              className={`transition-colors ${inlineSearchOpen ? 'text-yellow-400' : 'text-slate-500 hover:text-white'}`} title="Search in chat">
              <Search size={15} />
            </button>
          )}
          <button onClick={toggleSound} className={`transition-colors ${soundEnabled ? 'text-cyan-400 hover:text-cyan-300' : 'text-slate-600 hover:text-slate-400'}`} title={soundEnabled ? "Mute notifications" : "Unmute notifications"}>
            {soundEnabled ? <Bell size={15} /> : <BellOff size={15} />}
          </button>
          <button onClick={() => setCompact(!compact)} className="text-slate-500 hover:text-white transition-colors" title={compact ? "Expand chat" : "Compact chat"}>
            {compact ? <Maximize2 size={15} /> : <Minimize2 size={15} />}
          </button>
          <button onClick={handlePopOut} className="text-slate-500 hover:text-white transition-colors" title="Pop out chat">
            <ExternalLink size={15} />
          </button>
          <button onClick={closeSidebar} className="text-slate-500 hover:text-white transition-colors">
            <PanelRightClose size={18} />
          </button>
        </div>
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

          {/* BEACON AI Channel — only show user's private channel */}
          {channels.filter(c => c.channel_type === 'beacon' && c.name !== 'BEACON').slice(0, 1).map(ch => (
            <button
              key={ch.id}
              onClick={() => openChannel(ch)}
              className="w-full flex items-center gap-3 px-4 py-3 hover:bg-amber-500/[0.06] transition-colors border-b border-white/[0.03] text-left"
            >
              <div className="h-9 w-9 rounded-lg bg-gradient-to-br from-amber-500/20 to-orange-500/20 flex items-center justify-center flex-shrink-0">
                <Zap size={16} className="text-amber-400" />
              </div>
              <div className="flex-1 min-w-0">
                <div className="text-sm font-medium text-amber-300">BEACON</div>
                <div className="text-[10px] text-slate-500">AI Insurance Expert</div>
              </div>
              {(unreadMap[ch.id] || 0) > 0 && (
                <span className="h-5 min-w-[20px] px-1.5 rounded-full bg-amber-500 text-white text-[10px] font-bold flex items-center justify-center">
                  {unreadMap[ch.id]}
                </span>
              )}
            </button>
          ))}

          {/* DM Header */}
          <div className="flex items-center justify-between px-4 py-2 mt-1">
            <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">Direct Messages</span>
            <button onClick={() => setShowNewDM(!showNewDM)} className="px-2 py-0.5 text-[10px] font-bold text-cyan-300 bg-cyan-500/15 rounded hover:bg-cyan-500/25 transition-colors">
              {showNewDM ? 'Close' : '+ New DM'}
            </button>
          </div>

          {/* New DM User Picker */}
          {showNewDM && (
            <div className="mx-3 mb-2 bg-white/[0.05] rounded-lg border border-cyan-800/30 p-2 max-h-40 overflow-y-auto">
              <div className="text-[9px] text-slate-500 px-2 pb-1 mb-1 border-b border-white/[0.05]">Select a person to message:</div>
              {chatUsers.filter(u => u.role !== 'system' && u.username !== 'beacon.ai').map(u => (
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
          {/* Inline search bar */}
          {inlineSearchOpen && (
            <div className="flex items-center gap-1.5 px-3 py-2 bg-[#0d1a2e] border-b border-yellow-900/30">
              <Search size={13} className="text-yellow-500 flex-shrink-0" />
              <input
                value={inlineSearch}
                onChange={e => doInlineSearch(e.target.value)}
                onKeyDown={e => {
                  if (e.key === 'Enter') inlineSearchNav(e.shiftKey ? -1 : 1);
                  if (e.key === 'Escape') closeInlineSearch();
                }}
                placeholder="Find in conversation..."
                className="flex-1 bg-transparent text-xs text-slate-200 placeholder:text-slate-600 outline-none"
                autoFocus
              />
              {inlineMatchIds.length > 0 && (
                <span className="text-[10px] text-yellow-400 whitespace-nowrap">
                  {inlineMatchIdx + 1}/{inlineMatchIds.length}
                </span>
              )}
              {inlineSearch && inlineMatchIds.length === 0 && (
                <span className="text-[10px] text-slate-500">No results</span>
              )}
              <button onClick={() => inlineSearchNav(-1)} className="text-slate-500 hover:text-white" title="Previous">
                <ChevronLeft size={14} />
              </button>
              <button onClick={() => inlineSearchNav(1)} className="text-slate-500 hover:text-white" title="Next">
                <ChevronRight size={14} />
              </button>
              <button onClick={closeInlineSearch} className="text-slate-500 hover:text-white text-xs ml-1">✕</button>
            </div>
          )}
          <div ref={messagesContainerRef} onScroll={handleContainerScroll} className="flex-1 overflow-y-auto px-3 py-2 space-y-1" style={{ scrollbarWidth: 'thin', scrollbarColor: '#1e293b transparent' }}>
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
                const isBeacon = msg.sender_username === 'beacon.ai' || msg.sender_name === 'BEACON';
                const showAvatar = i === 0 || messages[i - 1]?.sender_id !== msg.sender_id;
                const isGif = msg.message_type === 'gif';

                const isMatch = inlineSearch && inlineMatchIds.includes(msg.id);
                const isCurrentMatch = isMatch && inlineMatchIds[inlineMatchIdx] === msg.id;

                return (
                  <div key={msg.id} id={`msg-${msg.id}`} className={`group ${showAvatar ? 'mt-3' : 'mt-0.5'} transition-all ${isCurrentMatch ? 'bg-yellow-500/10 rounded-lg ring-1 ring-yellow-500/30' : isMatch ? 'bg-yellow-500/5 rounded-lg' : ''}`}>
                    {/* Sender info */}
                    {showAvatar && (
                      <div className="flex items-center gap-2 mb-0.5">
                        {isBeacon ? (
                          <div className="h-6 w-6 rounded-full bg-gradient-to-br from-amber-400 to-orange-500 flex items-center justify-center flex-shrink-0">
                            <Zap size={11} className="text-white" />
                          </div>
                        ) : (
                          <div className="h-6 w-6 rounded-full flex items-center justify-center text-[8px] font-bold text-white flex-shrink-0"
                            style={{ background: initColor(msg.sender_name) }}>
                            {getInitials(msg.sender_name)}
                          </div>
                        )}
                        <span className={`text-xs font-semibold ${isBeacon ? 'text-amber-300' : 'text-slate-300'}`}>
                          {isMe ? 'You' : msg.sender_name}
                        </span>
                        <span className="text-[10px] text-slate-600">{formatTime(msg.created_at)}</span>
                      </div>
                    )}

                    {/* Reply reference */}
                    {msg.reply_to_id && (() => {
                      const original = messages.find((m: Message) => m.id === msg.reply_to_id);
                      return (
                        <div 
                          className="ml-8 mb-0.5 px-2 py-1 rounded bg-white/[0.03] border-l-2 border-cyan-800 text-[10px] text-slate-500 truncate cursor-pointer hover:bg-white/[0.06]"
                          onClick={() => {
                            const el = document.getElementById(`msg-${msg.reply_to_id}`);
                            if (el) { el.scrollIntoView({ behavior: 'smooth', block: 'center' }); el.classList.add('ring-1', 'ring-cyan-500/50'); setTimeout(() => el.classList.remove('ring-1', 'ring-cyan-500/50'), 2000); }
                          }}
                        >
                          {original ? (
                            <><span className="text-cyan-500 font-medium">{original.sender_name?.split(' ')[0]}</span>: {original.content?.slice(0, 80)}{(original.content?.length || 0) > 80 ? '...' : ''}</>
                          ) : (
                            <>↩ Reply</>
                          )}
                        </div>
                      );
                    })()}

                    {/* Per-message timestamp on hover (for grouped messages without header) */}
                    {!showAvatar && (
                      <div className="ml-8 hidden group-hover:flex items-center gap-1 mb-0.5">
                        <span className="text-[9px] text-slate-600">{formatTime(msg.created_at)}</span>
                      </div>
                    )}

                    {/* Message bubble */}
                    <div className={`ml-8 relative ${isGif ? '' : `rounded-lg px-3 py-1.5 text-sm max-w-[85%] ${
                      isBeacon ? 'bg-amber-500/[0.06] text-slate-200 border border-amber-500/10' :
                      isMe ? 'bg-cyan-600/20 text-cyan-100' : 'bg-white/[0.04] text-slate-300'
                    }`}`}>
                      {/* Content */}
                      {isGif ? (
                        <img src={msg.content || ''} alt="GIF" className="rounded-lg max-w-[200px] max-h-[150px]" loading="lazy" />
                      ) : msg.content ? (
                        isBeacon ? (
                          <div className="break-words whitespace-pre-wrap text-sm leading-relaxed"
                            dangerouslySetInnerHTML={{
                              __html: (msg.content || '')
                                .replace(/\*\*(.*?)\*\*/g, '<strong class="text-amber-200">$1</strong>')
                                .replace(/\*(.*?)\*/g, '<em>$1</em>')
                                .replace(/^• /gm, '&bull; ')
                                .replace(/^- /gm, '&bull; ')
                                .replace(/\n/g, '<br />')
                            }}
                          />
                        ) : (
                          <span className="break-words whitespace-pre-wrap"
                            dangerouslySetInnerHTML={{
                              __html: msg.content.replace(
                                /@(\w+)/g,
                                '<span class="text-cyan-400 font-semibold">@$1</span>'
                              )
                            }}
                          />
                        )
                      ) : null}

                      {/* File attachment */}
                      {msg.file_path && (
                        <div className="mt-1">
                          {msg.file_type && ['jpg', 'jpeg', 'png', 'gif', 'webp'].includes(msg.file_type) ? (
                            <a
                              href={`${API_BASE}${msg.file_path}`}
                              target="_blank"
                              rel="noopener noreferrer"
                            >
                              <img
                                src={`${API_BASE}${msg.file_path}`}
                                alt={msg.file_name || 'image'}
                                className="max-w-[280px] max-h-[200px] rounded-lg border border-white/[0.08] cursor-pointer hover:opacity-90 transition-opacity object-contain"
                                loading="lazy"
                              />
                            </a>
                          ) : (
                            <a
                              href={`${API_BASE}${msg.file_path}`}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="flex items-center gap-2 px-2 py-1.5 rounded bg-white/[0.04] hover:bg-white/[0.08] transition-colors border border-white/[0.06]"
                            >
                              <FileText size={14} className="text-amber-400" />
                              <span className="text-xs text-slate-300 truncate">{msg.file_name}</span>
                              <span className="text-[10px] text-slate-600 ml-auto">{msg.file_size ? `${(msg.file_size / 1024).toFixed(0)}KB` : ''}</span>
                            </a>
                          )}
                        </div>
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

                    {/* Seen by — show under last message in DMs and for mentions */}
                    {msg.seen_by && msg.seen_by.length > 0 && (
                      <div className="ml-8 flex items-center gap-1 mt-0.5">
                        <span className="text-[9px] text-slate-600">Seen by</span>
                        {msg.seen_by.map(s => (
                          <div key={s.user_id} title={`${s.name} · ${formatTime(s.read_at)}`}
                            className="h-3.5 w-3.5 rounded-full flex items-center justify-center text-[6px] font-bold text-white"
                            style={{ background: initColor(s.name) }}>
                            {getInitials(s.name)}
                          </div>
                        ))}
                        {msg.seen_by.length === 1 && (
                          <span className="text-[9px] text-slate-600">{msg.seen_by[0].name.split(' ')[0]}</span>
                        )}
                      </div>
                    )}

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
            {/* BEACON typing indicator */}
            {beaconTyping && activeChannel?.channel_type === 'beacon' && (
              <div className="mt-3">
                <div className="flex items-center gap-2 mb-0.5">
                  <div className="h-6 w-6 rounded-full bg-gradient-to-br from-amber-400 to-orange-500 flex items-center justify-center flex-shrink-0">
                    <Zap size={11} className="text-white" />
                  </div>
                  <span className="text-xs font-semibold text-amber-300">BEACON</span>
                  <span className="text-[10px] text-slate-500">is thinking...</span>
                </div>
                <div className="ml-8 flex items-center gap-1.5 py-1">
                  <div className="w-1.5 h-1.5 rounded-full bg-amber-400 animate-bounce" style={{ animationDelay: '0ms' }} />
                  <div className="w-1.5 h-1.5 rounded-full bg-amber-400 animate-bounce" style={{ animationDelay: '150ms' }} />
                  <div className="w-1.5 h-1.5 rounded-full bg-amber-400 animate-bounce" style={{ animationDelay: '300ms' }} />
                </div>
              </div>
            )}
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
              {file.type?.startsWith('image/') ? (
                <img src={URL.createObjectURL(file)} alt="preview" className="h-10 w-10 rounded object-cover border border-white/10" />
              ) : (
                <FileText size={12} className="text-amber-400" />
              )}
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
                onPaste={handlePaste}
                placeholder={activeChannel?.channel_type === 'beacon' ? "Ask BEACON about insurance..." : "Type a message... (@mention)"}
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
