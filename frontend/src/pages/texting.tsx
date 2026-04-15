import React, { useState, useEffect, useCallback, useRef } from 'react';
import Head from 'next/head';
import Navbar from '../components/Navbar';
import { useAuth } from '../contexts/AuthContext';
import {
  MessageCircle, Send, Search, Phone, User, Clock, CheckCircle,
  AlertCircle, ChevronLeft, RefreshCw, Smartphone, Monitor,
  ArrowDown, Zap, BarChart2, XCircle, Eye, EyeOff, Wifi, WifiOff,
  Plus, Loader2, MessageSquare, Settings, ChevronDown
} from 'lucide-react';
import axios from 'axios';
import { toast } from '../components/ui/Toast';

const API = process.env.NEXT_PUBLIC_API_URL || 'https://better-choice-api.onrender.com';

// ── Types ──────────────────────────────────────────────────────────

interface TextMessage {
  id: number; direction: string; phone_number: string; from_number: string;
  content: string; media_url: string; message_handle: string; status: string;
  service: string; customer_id: number | null; context: string; sent_by: string;
  was_downgraded: boolean | null; error_code: string | null;
  error_message: string | null; read: boolean;
  created_at: string;
}

interface Conversation {
  phone_number: string;
  last_message: {
    id: number; direction: string; content: string; status: string;
    service: string; created_at: string; media_url: string | null;
  };
  customer_id: number | null;
  customer_name: string | null;
  customer_email: string | null;
  unread_count: number;
  total_messages: number;
}

interface SendblueStats {
  total_messages: number; total_sent: number; total_received: number;
  today: number; this_week: number; unread: number;
  delivered: number; failed: number;
  imessage_count: number; sms_count: number;
  by_context: Record<string, number>;
}

// ── Helpers ────────────────────────────────────────────────────────

function timeAgo(d: string): string {
  const s = (Date.now() - new Date(d).getTime()) / 1000;
  if (s < 60) return 'now';
  if (s < 3600) return `${Math.floor(s / 60)}m`;
  if (s < 86400) return `${Math.floor(s / 3600)}h`;
  if (s < 172800) return 'yesterday';
  if (s < 604800) return `${Math.floor(s / 86400)}d`;
  return new Date(d).toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
}

function formatTime(d: string): string {
  return new Date(d).toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' });
}

function formatDate(d: string): string {
  const dt = new Date(d);
  const today = new Date();
  const yesterday = new Date(today); yesterday.setDate(today.getDate() - 1);
  if (dt.toDateString() === today.toDateString()) return 'Today';
  if (dt.toDateString() === yesterday.toDateString()) return 'Yesterday';
  return dt.toLocaleDateString('en-US', { weekday: 'long', month: 'short', day: 'numeric' });
}

function formatPhone(p: string): string {
  const d = p.replace(/\D/g, '');
  const n = d.startsWith('1') ? d.slice(1) : d;
  if (n.length === 10) return `(${n.slice(0, 3)}) ${n.slice(3, 6)}-${n.slice(6)}`;
  return p;
}

function getInitials(name: string): string {
  if (!name) return '?';
  const parts = name.trim().split(/\s+/);
  return parts.length >= 2 ? (parts[0][0] + parts[parts.length - 1][0]).toUpperCase() : name.slice(0, 2).toUpperCase();
}

function initialsColor(s: string): string {
  const colors = ['#3b82f6', '#8b5cf6', '#ec4899', '#f97316', '#10b981', '#06b6d4', '#6366f1', '#ef4444'];
  let h = 0;
  for (let i = 0; i < s.length; i++) h = s.charCodeAt(i) + ((h << 5) - h);
  return colors[Math.abs(h) % colors.length];
}

const STATUS_ICON: Record<string, { icon: React.ReactNode; color: string; label: string }> = {
  DELIVERED: { icon: <CheckCircle size={10} />, color: '#34d399', label: 'Delivered' },
  SENT: { icon: <CheckCircle size={10} />, color: '#60a5fa', label: 'Sent' },
  QUEUED: { icon: <Clock size={10} />, color: '#fbbf24', label: 'Queued' },
  ACCEPTED: { icon: <Clock size={10} />, color: '#818cf8', label: 'Sending' },
  PENDING: { icon: <Clock size={10} />, color: '#94a3b8', label: 'Pending' },
  ERROR: { icon: <AlertCircle size={10} />, color: '#f87171', label: 'Failed' },
  DECLINED: { icon: <XCircle size={10} />, color: '#ef4444', label: 'Declined' },
  RECEIVED: { icon: <CheckCircle size={10} />, color: '#34d399', label: 'Received' },
};

// ── Main Component ─────────────────────────────────────────────────

export default function TextingPage() {
  const { user } = useAuth();
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [selectedPhone, setSelectedPhone] = useState<string | null>(null);
  const [messages, setMessages] = useState<TextMessage[]>([]);
  const [stats, setStats] = useState<SendblueStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [messagesLoading, setMessagesLoading] = useState(false);
  const [sending, setSending] = useState(false);
  const [draft, setDraft] = useState('');
  const [searchTerm, setSearchTerm] = useState('');
  const [showNewMessage, setShowNewMessage] = useState(false);
  const [newNumber, setNewNumber] = useState('');
  const [view, setView] = useState<'conversations' | 'stats'>('conversations');
  const [customerInfo, setCustomerInfo] = useState<any>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Admin gate
  const isAdmin = user?.role?.toLowerCase() === 'admin';

  // ── Fetch conversations ────────────────────────────────────────
  const fetchConversations = useCallback(async () => {
    try {
      const { data } = await axios.get(`${API}/api/sendblue/conversations?limit=100`);
      setConversations(data.conversations || []);
    } catch (e) {
      console.error('Failed to load conversations:', e);
    } finally {
      setLoading(false);
    }
  }, []);

  // ── Fetch thread ───────────────────────────────────────────────
  const fetchThread = useCallback(async (phone: string) => {
    setMessagesLoading(true);
    try {
      const { data } = await axios.get(`${API}/api/sendblue/conversation/${encodeURIComponent(phone)}?limit=100`);
      setMessages(data.messages || []);
      setCustomerInfo(data.customer || null);
      // Update unread count in conversation list
      setConversations(prev => prev.map(c =>
        c.phone_number === phone ? { ...c, unread_count: 0 } : c
      ));
    } catch (e) {
      console.error('Failed to load thread:', e);
      toast.error('Failed to load conversation');
    } finally {
      setMessagesLoading(false);
    }
  }, []);

  // ── Fetch stats ────────────────────────────────────────────────
  const fetchStats = useCallback(async () => {
    try {
      const { data } = await axios.get(`${API}/api/sendblue/stats`);
      setStats(data);
    } catch (e) {
      console.error('Failed to load stats:', e);
    }
  }, []);

  // ── Send message ───────────────────────────────────────────────
  const handleSend = async () => {
    const phone = showNewMessage ? newNumber : selectedPhone;
    if (!phone || !draft.trim()) return;
    setSending(true);
    try {
      await axios.post(`${API}/api/sendblue/send`, {
        to_number: phone,
        content: draft.trim(),
        context: 'manual',
      });
      setDraft('');
      if (showNewMessage) {
        setShowNewMessage(false);
        setNewNumber('');
        setSelectedPhone(phone);
      }
      // Refresh thread
      if (selectedPhone) await fetchThread(selectedPhone);
      else if (phone) {
        setSelectedPhone(phone);
        await fetchThread(phone);
      }
      await fetchConversations();
      toast.success('Message sent');
    } catch (e: any) {
      toast.error(e.response?.data?.detail || 'Failed to send message');
    } finally {
      setSending(false);
    }
  };

  // ── Effects ────────────────────────────────────────────────────
  useEffect(() => {
    if (!isAdmin) return;
    fetchConversations();
    fetchStats();
  }, [isAdmin, fetchConversations, fetchStats]);

  useEffect(() => {
    if (selectedPhone) {
      fetchThread(selectedPhone);
    }
  }, [selectedPhone, fetchThread]);

  // Auto-scroll to bottom
  useEffect(() => {
    if (messagesEndRef.current) {
      messagesEndRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [messages]);

  // Poll for new messages every 10 seconds
  useEffect(() => {
    if (!isAdmin) return;
    pollRef.current = setInterval(() => {
      fetchConversations();
      if (selectedPhone) fetchThread(selectedPhone);
    }, 10000);
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, [isAdmin, selectedPhone, fetchConversations, fetchThread]);

  // Focus input when conversation selected
  useEffect(() => {
    if (selectedPhone && inputRef.current) {
      setTimeout(() => inputRef.current?.focus(), 100);
    }
  }, [selectedPhone]);

  // ── Access gate ────────────────────────────────────────────────
  if (!user) {
    return (
      <>
        <Head><title>Texting — ORBIT</title></Head>
        <Navbar />
        <div className="min-h-screen bg-[#080e1a] flex items-center justify-center">
          <Loader2 className="animate-spin text-blue-500" size={32} />
        </div>
      </>
    );
  }

  if (!isAdmin) {
    return (
      <>
        <Head><title>Texting — ORBIT</title></Head>
        <Navbar />
        <div className="min-h-screen bg-[#080e1a] flex items-center justify-center">
          <div className="text-center">
            <Smartphone size={48} className="mx-auto text-slate-600 mb-4" />
            <h2 className="text-xl font-bold text-slate-300 mb-2">Texting — Admin Only</h2>
            <p className="text-sm text-slate-500">This feature is currently restricted to admin users.</p>
          </div>
        </div>
      </>
    );
  }

  // ── Filter conversations ───────────────────────────────────────
  const filtered = conversations.filter(c => {
    if (!searchTerm) return true;
    const s = searchTerm.toLowerCase();
    return (
      c.phone_number.includes(s) ||
      (c.customer_name || '').toLowerCase().includes(s) ||
      (c.last_message.content || '').toLowerCase().includes(s)
    );
  });

  const totalUnread = conversations.reduce((n, c) => n + c.unread_count, 0);

  // ── Group messages by date ─────────────────────────────────────
  const groupedMessages: { date: string; messages: TextMessage[] }[] = [];
  messages.forEach(m => {
    const dateStr = formatDate(m.created_at);
    const last = groupedMessages[groupedMessages.length - 1];
    if (last && last.date === dateStr) {
      last.messages.push(m);
    } else {
      groupedMessages.push({ date: dateStr, messages: [m] });
    }
  });

  return (
    <>
      <Head><title>Texting — ORBIT</title></Head>
      <Navbar />
      <div className="min-h-screen bg-[#080e1a] pt-16">
        <div className="h-[calc(100vh-64px)] flex">

          {/* ── LEFT SIDEBAR: Conversations ─────────────────────── */}
          <div className={`w-[360px] flex-shrink-0 border-r border-white/[0.06] flex flex-col bg-[#0a1220] ${selectedPhone ? 'hidden md:flex' : 'flex'}`}>

            {/* Header */}
            <div className="p-4 border-b border-white/[0.06]">
              <div className="flex items-center justify-between mb-3">
                <div className="flex items-center gap-2">
                  <MessageCircle size={18} className="text-blue-400" />
                  <h1 className="text-[15px] font-bold text-white">Texting</h1>
                  {totalUnread > 0 && (
                    <span className="px-1.5 py-0.5 rounded-full bg-blue-500 text-[10px] font-bold text-white min-w-[18px] text-center">
                      {totalUnread}
                    </span>
                  )}
                </div>
                <div className="flex items-center gap-1">
                  <button onClick={() => setView(view === 'stats' ? 'conversations' : 'stats')}
                    className={`p-1.5 rounded-lg transition-colors ${view === 'stats' ? 'bg-blue-500/20 text-blue-400' : 'text-slate-500 hover:text-slate-300 hover:bg-white/[0.04]'}`}
                    title="Stats">
                    <BarChart2 size={14} />
                  </button>
                  <button onClick={() => { setShowNewMessage(true); setSelectedPhone(null); }}
                    className="p-1.5 rounded-lg text-slate-500 hover:text-blue-400 hover:bg-white/[0.04] transition-colors"
                    title="New message">
                    <Plus size={14} />
                  </button>
                  <button onClick={() => { fetchConversations(); fetchStats(); }}
                    className="p-1.5 rounded-lg text-slate-500 hover:text-slate-300 hover:bg-white/[0.04] transition-colors"
                    title="Refresh">
                    <RefreshCw size={14} />
                  </button>
                </div>
              </div>

              {/* Search */}
              <div className="relative">
                <Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-600" />
                <input
                  value={searchTerm}
                  onChange={e => setSearchTerm(e.target.value)}
                  placeholder="Search conversations..."
                  className="w-full pl-8 pr-3 py-1.5 bg-white/[0.04] border border-white/[0.06] rounded-lg text-[12px] text-slate-300 placeholder-slate-600 focus:outline-none focus:border-blue-500/30"
                />
              </div>
            </div>

            {/* Stats View */}
            {view === 'stats' && stats && (
              <div className="flex-1 overflow-y-auto p-4 space-y-3">
                <div className="grid grid-cols-2 gap-2">
                  {[
                    { label: 'Total Sent', value: stats.total_sent, color: 'text-blue-400' },
                    { label: 'Total Received', value: stats.total_received, color: 'text-emerald-400' },
                    { label: 'Today', value: stats.today, color: 'text-cyan-400' },
                    { label: 'This Week', value: stats.this_week, color: 'text-violet-400' },
                    { label: 'Delivered', value: stats.delivered, color: 'text-green-400' },
                    { label: 'Failed', value: stats.failed, color: 'text-red-400' },
                    { label: 'iMessage', value: stats.imessage_count, icon: <Smartphone size={11} className="text-blue-400" /> },
                    { label: 'SMS', value: stats.sms_count, icon: <MessageSquare size={11} className="text-green-400" /> },
                  ].map((s, i) => (
                    <div key={i} className="bg-white/[0.03] border border-white/[0.06] rounded-lg p-3">
                      <div className="flex items-center gap-1 mb-1">
                        {(s as any).icon || null}
                        <span className="text-[10px] text-slate-500 uppercase tracking-wider">{s.label}</span>
                      </div>
                      <span className={`text-lg font-bold ${(s as any).color || 'text-white'}`}>{s.value}</span>
                    </div>
                  ))}
                </div>
                {stats.unread > 0 && (
                  <div className="bg-blue-500/10 border border-blue-500/20 rounded-lg p-3 flex items-center gap-2">
                    <Eye size={14} className="text-blue-400" />
                    <span className="text-[12px] text-blue-300">{stats.unread} unread message{stats.unread !== 1 ? 's' : ''}</span>
                  </div>
                )}
              </div>
            )}

            {/* Conversation List */}
            {view === 'conversations' && (
              <div className="flex-1 overflow-y-auto">
                {loading ? (
                  <div className="flex justify-center py-12">
                    <Loader2 className="animate-spin text-slate-600" size={20} />
                  </div>
                ) : filtered.length === 0 ? (
                  <div className="text-center py-12">
                    <MessageCircle size={32} className="mx-auto text-slate-700 mb-3" />
                    <p className="text-sm text-slate-500">{searchTerm ? 'No matching conversations' : 'No conversations yet'}</p>
                    <p className="text-xs text-slate-600 mt-1">Send a text to get started</p>
                  </div>
                ) : (
                  filtered.map(conv => {
                    const isSelected = selectedPhone === conv.phone_number;
                    const displayName = conv.customer_name || formatPhone(conv.phone_number);
                    const isInbound = conv.last_message.direction === 'inbound';
                    const statusInfo = STATUS_ICON[conv.last_message.status] || null;

                    return (
                      <button
                        key={conv.phone_number}
                        onClick={() => { setSelectedPhone(conv.phone_number); setShowNewMessage(false); }}
                        className={`w-full text-left px-4 py-3 border-b border-white/[0.03] transition-colors ${
                          isSelected
                            ? 'bg-blue-500/10 border-l-2 border-l-blue-500'
                            : 'hover:bg-white/[0.03] border-l-2 border-l-transparent'
                        }`}
                      >
                        <div className="flex items-start gap-3">
                          {/* Avatar */}
                          <div className="w-9 h-9 rounded-full flex items-center justify-center text-[11px] font-bold text-white flex-shrink-0 mt-0.5"
                            style={{ background: initialsColor(displayName) }}>
                            {getInitials(displayName)}
                          </div>
                          {/* Content */}
                          <div className="flex-1 min-w-0">
                            <div className="flex items-center justify-between">
                              <span className={`text-[13px] font-semibold truncate ${conv.unread_count > 0 ? 'text-white' : 'text-slate-300'}`}>
                                {displayName}
                              </span>
                              <span className="text-[10px] text-slate-600 flex-shrink-0 ml-2">
                                {conv.last_message.created_at ? timeAgo(conv.last_message.created_at) : ''}
                              </span>
                            </div>
                            {conv.customer_name && (
                              <p className="text-[10px] text-slate-600 truncate">{formatPhone(conv.phone_number)}</p>
                            )}
                            <div className="flex items-center gap-1 mt-0.5">
                              {!isInbound && statusInfo && (
                                <span style={{ color: statusInfo.color }}>{statusInfo.icon}</span>
                              )}
                              <p className={`text-[11px] truncate ${conv.unread_count > 0 ? 'text-slate-200 font-medium' : 'text-slate-500'}`}>
                                {!isInbound && <span className="text-slate-600">You: </span>}
                                {conv.last_message.content || (conv.last_message.media_url ? '📎 Attachment' : '...')}
                              </p>
                            </div>
                          </div>
                          {/* Unread badge */}
                          {conv.unread_count > 0 && (
                            <span className="px-1.5 py-0.5 rounded-full bg-blue-500 text-[9px] font-bold text-white min-w-[16px] text-center flex-shrink-0 mt-2">
                              {conv.unread_count}
                            </span>
                          )}
                        </div>

                        {/* Service badge */}
                        {conv.last_message.service && (
                          <div className="mt-1 ml-12">
                            <span className={`inline-flex items-center gap-0.5 text-[9px] px-1.5 py-0.5 rounded-full ${
                              conv.last_message.service.toLowerCase().includes('imessage')
                                ? 'bg-blue-500/10 text-blue-400'
                                : 'bg-emerald-500/10 text-emerald-400'
                            }`}>
                              {conv.last_message.service.toLowerCase().includes('imessage') ? (
                                <><Smartphone size={8} /> iMessage</>
                              ) : (
                                <><MessageSquare size={8} /> SMS</>
                              )}
                            </span>
                          </div>
                        )}
                      </button>
                    );
                  })
                )}
              </div>
            )}
          </div>

          {/* ── RIGHT PANEL: Thread / New Message / Empty ────────── */}
          <div className="flex-1 flex flex-col bg-[#080e1a]">

            {/* New Message Compose */}
            {showNewMessage && (
              <>
                <div className="px-4 py-3 border-b border-white/[0.06] bg-[#0a1220]">
                  <div className="flex items-center gap-2">
                    <button onClick={() => setShowNewMessage(false)} className="md:hidden p-1 text-slate-400 hover:text-white">
                      <ChevronLeft size={18} />
                    </button>
                    <Plus size={16} className="text-blue-400" />
                    <span className="text-[14px] font-semibold text-white">New Message</span>
                  </div>
                  <div className="mt-3 flex items-center gap-2">
                    <span className="text-[12px] text-slate-500">To:</span>
                    <input
                      value={newNumber}
                      onChange={e => setNewNumber(e.target.value)}
                      placeholder="Phone number (e.g. 847-908-5665)"
                      className="flex-1 bg-transparent text-[13px] text-white placeholder-slate-600 focus:outline-none"
                      autoFocus
                    />
                  </div>
                </div>
                {/* Spacer + compose pinned to bottom */}
                <div className="flex-1 flex flex-col justify-end">
                  <div className="px-4 py-3 border-t border-white/[0.06] bg-[#0a1220]">
                    <div className="flex items-end gap-2">
                      <textarea
                        ref={inputRef}
                        value={draft}
                        onChange={e => setDraft(e.target.value)}
                        onKeyDown={e => {
                          if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend(); }
                        }}
                        placeholder="Type a message..."
                        rows={2}
                        className="flex-1 bg-white/[0.06] border border-white/[0.1] rounded-xl px-4 py-2.5 text-[13px] text-white placeholder-slate-500 focus:outline-none focus:border-blue-500/40 resize-none"
                        style={{ minHeight: '52px' }}
                      />
                      <button
                        onClick={handleSend}
                        disabled={sending || !draft.trim() || !newNumber.trim()}
                        className="p-2.5 rounded-xl bg-blue-600 hover:bg-blue-500 text-white disabled:opacity-30 disabled:hover:bg-blue-600 transition-colors flex-shrink-0"
                      >
                        {sending ? <Loader2 size={16} className="animate-spin" /> : <Send size={16} />}
                      </button>
                    </div>
                    <p className="text-[10px] text-slate-600 mt-1.5 px-1">Enter to send · Shift+Enter for new line</p>
                  </div>
                </div>
              </>
            )}

            {/* Empty state */}
            {!showNewMessage && !selectedPhone && (
              <div className="flex-1 flex items-center justify-center">
                <div className="text-center">
                  <div className="w-20 h-20 rounded-2xl bg-gradient-to-br from-blue-500/20 to-cyan-500/10 border border-blue-500/10 flex items-center justify-center mx-auto mb-4">
                    <MessageCircle size={32} className="text-blue-400/60" />
                  </div>
                  <h3 className="text-lg font-semibold text-slate-300 mb-1">ORBIT Texting</h3>
                  <p className="text-sm text-slate-500 mb-4">iMessage & SMS powered by Sendblue</p>
                  <button
                    onClick={() => setShowNewMessage(true)}
                    className="inline-flex items-center gap-1.5 px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white text-[13px] font-medium rounded-lg transition-colors"
                  >
                    <Plus size={14} /> New Message
                  </button>
                </div>
              </div>
            )}

            {/* Active Thread */}
            {!showNewMessage && selectedPhone && (
              <>
                {/* Thread Header */}
                <div className="px-4 py-3 border-b border-white/[0.06] bg-[#0a1220] flex items-center gap-3">
                  <button onClick={() => setSelectedPhone(null)} className="md:hidden p-1 text-slate-400 hover:text-white">
                    <ChevronLeft size={18} />
                  </button>
                  <div className="w-9 h-9 rounded-full flex items-center justify-center text-[11px] font-bold text-white flex-shrink-0"
                    style={{ background: initialsColor(customerInfo?.name || selectedPhone) }}>
                    {getInitials(customerInfo?.name || selectedPhone)}
                  </div>
                  <div className="flex-1 min-w-0">
                    <h2 className="text-[14px] font-semibold text-white truncate">
                      {customerInfo?.name || formatPhone(selectedPhone)}
                    </h2>
                    <div className="flex items-center gap-2">
                      <span className="text-[11px] text-slate-500">{formatPhone(selectedPhone)}</span>
                      {customerInfo?.email && (
                        <span className="text-[11px] text-slate-600">· {customerInfo.email}</span>
                      )}
                    </div>
                  </div>
                  <button onClick={() => { fetchThread(selectedPhone); fetchConversations(); }}
                    className="p-1.5 rounded-lg text-slate-500 hover:text-slate-300 hover:bg-white/[0.04] transition-colors">
                    <RefreshCw size={14} />
                  </button>
                </div>

                {/* Messages */}
                <div className="flex-1 overflow-y-auto px-4 py-4 space-y-1">
                  {messagesLoading ? (
                    <div className="flex justify-center py-12">
                      <Loader2 className="animate-spin text-slate-600" size={20} />
                    </div>
                  ) : messages.length === 0 ? (
                    <div className="flex justify-center py-12">
                      <p className="text-sm text-slate-600">No messages yet. Start the conversation!</p>
                    </div>
                  ) : (
                    groupedMessages.map((group, gi) => (
                      <div key={gi}>
                        {/* Date divider */}
                        <div className="flex items-center justify-center my-4">
                          <span className="px-3 py-1 rounded-full bg-white/[0.04] text-[10px] text-slate-500 font-medium">
                            {group.date}
                          </span>
                        </div>
                        {/* Messages in this date group */}
                        {group.messages.map((msg, mi) => {
                          const isOutbound = msg.direction === 'outbound';
                          const statusInfo = STATUS_ICON[msg.status] || null;
                          const isIMessage = (msg.service || '').toLowerCase().includes('imessage');

                          return (
                            <div key={msg.id} className={`flex ${isOutbound ? 'justify-end' : 'justify-start'} mb-1.5`}>
                              <div className={`max-w-[75%] group`}>
                                <div className={`rounded-2xl px-3.5 py-2 ${
                                  isOutbound
                                    ? isIMessage
                                      ? 'bg-blue-600 text-white rounded-br-md'
                                      : 'bg-emerald-600 text-white rounded-br-md'
                                    : 'bg-white/[0.06] text-slate-200 border border-white/[0.06] rounded-bl-md'
                                }`}>
                                  {/* Content */}
                                  <p className="text-[13px] leading-relaxed whitespace-pre-wrap break-words">
                                    {msg.content || (msg.media_url ? '' : '...')}
                                  </p>
                                  {/* Media */}
                                  {msg.media_url && (
                                    <a href={msg.media_url} target="_blank" rel="noopener noreferrer"
                                      className="mt-1 inline-flex items-center gap-1 text-[11px] underline opacity-80 hover:opacity-100">
                                      📎 Attachment
                                    </a>
                                  )}
                                </div>
                                {/* Meta row */}
                                <div className={`flex items-center gap-1.5 mt-0.5 px-1 ${isOutbound ? 'justify-end' : 'justify-start'}`}>
                                  <span className="text-[9px] text-slate-600">{formatTime(msg.created_at)}</span>
                                  {isOutbound && statusInfo && (
                                    <span className="flex items-center gap-0.5 text-[9px]" style={{ color: statusInfo.color }}>
                                      {statusInfo.icon}
                                      <span className="opacity-0 group-hover:opacity-100 transition-opacity">{statusInfo.label}</span>
                                    </span>
                                  )}
                                  {isOutbound && msg.service && (
                                    <span className={`text-[9px] opacity-0 group-hover:opacity-100 transition-opacity ${
                                      isIMessage ? 'text-blue-400' : 'text-emerald-400'
                                    }`}>
                                      {isIMessage ? 'iMessage' : 'SMS'}
                                    </span>
                                  )}
                                  {isOutbound && msg.sent_by && (
                                    <span className="text-[9px] text-slate-700 opacity-0 group-hover:opacity-100 transition-opacity">
                                      · {msg.sent_by}
                                    </span>
                                  )}
                                  {msg.context && msg.context !== 'manual' && msg.context !== 'inbound_webhook' && (
                                    <span className="text-[9px] text-violet-500/60 opacity-0 group-hover:opacity-100 transition-opacity">
                                      · {msg.context}
                                    </span>
                                  )}
                                </div>
                              </div>
                            </div>
                          );
                        })}
                      </div>
                    ))
                  )}
                  <div ref={messagesEndRef} />
                </div>

                {/* Compose bar */}
                <div className="px-4 py-3 border-t border-white/[0.06] bg-[#0a1220]">
                  <div className="flex items-end gap-2">
                    <textarea
                      ref={inputRef}
                      value={draft}
                      onChange={e => {
                        setDraft(e.target.value);
                        // Auto-resize
                        const el = e.target;
                        el.style.height = 'auto';
                        el.style.height = Math.min(el.scrollHeight, 128) + 'px';
                      }}
                      onKeyDown={e => {
                        if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend(); }
                      }}
                      placeholder="iMessage"
                      rows={1}
                      className="flex-1 bg-white/[0.04] border border-white/[0.08] rounded-xl px-4 py-2.5 text-[13px] text-white placeholder-slate-600 focus:outline-none focus:border-blue-500/30 resize-none"
                      style={{ minHeight: '40px', maxHeight: '128px' }}
                    />
                    <button
                      onClick={handleSend}
                      disabled={sending || !draft.trim()}
                      className="p-2.5 rounded-xl bg-blue-600 hover:bg-blue-500 text-white disabled:opacity-30 disabled:hover:bg-blue-600 transition-colors flex-shrink-0"
                    >
                      {sending ? <Loader2 size={16} className="animate-spin" /> : <Send size={16} />}
                    </button>
                  </div>
                  <div className="flex items-center justify-between mt-1.5 px-1">
                    <span className="text-[10px] text-slate-700">
                      Shift+Enter for new line
                    </span>
                    <span className="text-[10px] text-slate-700">
                      {draft.length > 0 ? `${draft.length} / 18,996` : ''}
                    </span>
                  </div>
                </div>
              </>
            )}
          </div>
        </div>
      </div>
    </>
  );
}
