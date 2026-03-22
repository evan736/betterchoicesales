import React, { useEffect, useState, useRef, useCallback } from 'react';
import { useAuth } from '../contexts/AuthContext';
import Navbar from '../components/Navbar';
import { emailAPI } from '../lib/api';
import {
  Mail, Search, Inbox, Send, User, Clock, Tag, ChevronDown, ChevronRight,
  Loader2, X, CheckCircle2, AlertCircle, Paperclip, FileText, Sparkles,
  Archive, RefreshCw, ArrowLeft, MailOpen, Star, Users, Filter,
  Zap, ListChecks, AlertTriangle, ArrowRight, MailPlus,
} from 'lucide-react';
import { toast } from '../components/ui/Toast';

const TAGS = ['billing', 'claims', 'new-business', 'endorsement', 'renewal', 'general', 'urgent'];

export default function InboxPage() {
  const { user } = useAuth();
  const [threads, setThreads] = useState<any[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [stats, setStats] = useState<any>({});
  const [activeThread, setActiveThread] = useState<any>(null);
  const [messages, setMessages] = useState<any[]>([]);
  const [threadLoading, setThreadLoading] = useState(false);
  const [employees, setEmployees] = useState<any[]>([]);

  // Mailboxes
  const [mailboxes, setMailboxes] = useState<any[]>([]);
  const [activeMailbox, setActiveMailbox] = useState('service');
  const [isAdmin, setIsAdmin] = useState(false);
  const [canAssignAnyone, setCanAssignAnyone] = useState(false);
  const [userMailbox, setUserMailbox] = useState('');

  // Filters
  const [filterStatus, setFilterStatus] = useState('');
  const [searchQuery, setSearchQuery] = useState('');
  const [page, setPage] = useState(1);

  // Reply state
  const [replyOpen, setReplyOpen] = useState(false);
  const [replyBody, setReplyBody] = useState('');
  const [replyCc, setReplyCc] = useState('');
  const [replySendAs, setReplySendAs] = useState<'service' | 'personal'>('service');
  const [replyFiles, setReplyFiles] = useState<File[]>([]);
  const [replySending, setReplySending] = useState(false);
  const [closeAfterReply, setCloseAfterReply] = useState(false);
  const replyFileRef = useRef<HTMLInputElement>(null);

  // AI Draft + Action Items
  const [aiDraft, setAiDraft] = useState('');
  const [aiActionItems, setAiActionItems] = useState<string[]>([]);
  const [aiUrgency, setAiUrgency] = useState('normal');
  const [aiSummary, setAiSummary] = useState('');
  const [aiLoading, setAiLoading] = useState(false);

  const messagesEndRef = useRef<HTMLDivElement>(null);

  const loadMailboxes = async () => {
    try {
      const res = await emailAPI.mailboxes();
      setMailboxes(res.data.mailboxes);
      setIsAdmin(res.data.is_admin);
      setCanAssignAnyone(res.data.can_assign_anyone);
      setUserMailbox(res.data.user_mailbox);
    } catch (e) { console.error(e); }
  };

  const loadThreads = useCallback(async () => {
    setLoading(true);
    try {
      const params: any = { page, page_size: 30, mailbox: activeMailbox };
      if (filterStatus) params.status = filterStatus;
      if (searchQuery) params.search = searchQuery;
      const res = await emailAPI.threads(params);
      setThreads(res.data.threads);
      setTotal(res.data.total);
    } catch (e) { console.error(e); }
    finally { setLoading(false); }
  }, [page, activeMailbox, filterStatus, searchQuery]);

  const loadStats = async () => {
    try { const res = await emailAPI.stats(); setStats(res.data); } catch {}
  };

  const loadEmployees = async () => {
    try {
      const { chatAPI } = await import('../lib/api');
      const res = await chatAPI.listUsers();
      setEmployees(res.data);
    } catch {}
  };

  useEffect(() => { loadMailboxes(); loadEmployees(); }, []);
  useEffect(() => { loadThreads(); loadStats(); }, [loadThreads]);

  const switchMailbox = (mb: string) => {
    setActiveMailbox(mb);
    setActiveThread(null);
    setPage(1);
    setAiDraft(''); setAiActionItems([]); setAiSummary('');
  };

  const openThread = async (thread: any) => {
    setActiveThread(thread);
    setReplyOpen(false);
    setAiDraft(''); setAiActionItems([]); setAiSummary(''); setAiUrgency('normal');
    setThreadLoading(true);
    try {
      const res = await emailAPI.thread(thread.id);
      setActiveThread(res.data.thread);
      setMessages(res.data.messages);
      setThreads(prev => prev.map(t => t.id === thread.id ? { ...t, is_unread: false } : t));
    } catch (e) { console.error(e); }
    finally { setThreadLoading(false); }
  };

  const handleReply = async () => {
    if (!activeThread || !replyBody.trim()) return;
    setReplySending(true);
    try {
      await emailAPI.reply(activeThread.id, {
        body: replyBody,
        cc_emails: replyCc || undefined,
        send_as: replySendAs,
        close_after: closeAfterReply,
        attachments: replyFiles.length > 0 ? replyFiles : undefined,
      });
      setReplyBody(''); setReplyCc(''); setReplyFiles([]); setReplyOpen(false);
      if (closeAfterReply) { setActiveThread(null); loadThreads(); }
      else { openThread(activeThread); }
      loadStats(); loadMailboxes();
    } catch (e: any) { toast.error(e.response?.data?.detail || 'Failed to send'); }
    finally { setReplySending(false); }
  };

  const handleAiDraft = async () => {
    if (!activeThread) return;
    setAiLoading(true);
    try {
      const res = await emailAPI.aiDraft(activeThread.id);
      setAiDraft(res.data.draft);
      setAiActionItems(res.data.action_items || []);
      setAiUrgency(res.data.urgency || 'normal');
      setAiSummary(res.data.summary || '');
      setReplyBody(res.data.draft);
      setReplyOpen(true);
    } catch (e: any) { toast.error(e.response?.data?.detail || 'AI draft failed'); }
    finally { setAiLoading(false); }
  };

  const handleAssign = async (threadId: number, userId: number | null) => {
    try {
      await emailAPI.assign(threadId, userId);
      if (activeThread?.id === threadId) openThread(activeThread);
      loadThreads(); loadStats();
    } catch (e) { console.error(e); }
  };

  const handleStatus = async (threadId: number, status: string) => {
    try {
      await emailAPI.setStatus(threadId, status);
      if (status === 'closed') { setActiveThread(null); }
      loadThreads(); loadStats(); loadMailboxes();
    } catch (e) { console.error(e); }
  };

  const formatTime = (iso: string) => {
    if (!iso) return '';
    const d = new Date(iso);
    const now = new Date();
    const diffMs = now.getTime() - d.getTime();
    if (diffMs < 60000) return 'Just now';
    if (diffMs < 3600000) return `${Math.floor(diffMs / 60000)}m ago`;
    if (diffMs < 86400000) return d.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' });
    if (diffMs < 604800000) return d.toLocaleDateString('en-US', { weekday: 'short', hour: 'numeric', minute: '2-digit' });
    return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' });
  };

  const getInitials = (name: string) => name?.split(' ').map(w => w[0]).join('').slice(0, 2).toUpperCase() || '?';
  const initColor = (name: string) => {
    const colors = ['#06b6d4', '#8b5cf6', '#f59e0b', '#10b981', '#ef4444', '#ec4899', '#6366f1', '#14b8a6'];
    let h = 0; for (let i = 0; i < (name || '').length; i++) h = name.charCodeAt(i) + ((h << 5) - h);
    return colors[Math.abs(h) % colors.length];
  };

  const mailboxLabel = (mb: string) => {
    if (mb === 'service') return 'Service Inbox';
    return mb.split('.').map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' ');
  };

  const urgencyColor: Record<string, string> = {
    low: 'text-slate-400', normal: 'text-blue-500', high: 'text-amber-500', urgent: 'text-red-500',
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

  return (
    <div className="min-h-screen bg-slate-50">
      <Navbar />
      <div className="flex" style={{ height: 'calc(100vh - 64px)' }}>

        {/* ═══ LEFT: Mailbox Sidebar ═══ */}
        <div className="w-52 flex-shrink-0 border-r border-slate-200 bg-slate-50 flex flex-col">
          <div className="px-3 py-3 border-b border-slate-200">
            <h3 className="text-[10px] font-bold text-slate-400 uppercase tracking-wider mb-2">Mailboxes</h3>
            {mailboxes.map(mb => (
              <button key={mb.mailbox} onClick={() => switchMailbox(mb.mailbox)}
                className={`w-full flex items-center justify-between px-2.5 py-1.5 rounded-lg text-sm transition-colors mb-0.5 ${
                  activeMailbox === mb.mailbox
                    ? 'bg-blue-100 text-blue-700 font-semibold'
                    : 'text-slate-600 hover:bg-slate-100'
                }`}>
                <span className="flex items-center gap-2 truncate">
                  {mb.mailbox === 'service' ? <Inbox size={14} /> : <User size={14} />}
                  <span className="truncate">{mailboxLabel(mb.mailbox)}</span>
                </span>
                {mb.open_count > 0 && (
                  <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded-full ${
                    activeMailbox === mb.mailbox ? 'bg-blue-200 text-blue-800' : 'bg-slate-200 text-slate-600'
                  }`}>{mb.open_count}</span>
                )}
              </button>
            ))}
          </div>

          {/* Quick stats */}
          <div className="px-3 py-3 space-y-1.5 text-[11px]">
            <div className="flex justify-between text-slate-500"><span>Open</span><span className="font-bold text-blue-600">{stats.open || 0}</span></div>
            <div className="flex justify-between text-slate-500"><span>Unassigned</span><span className="font-bold text-amber-600">{stats.unassigned || 0}</span></div>
            <div className="flex justify-between text-slate-500"><span>My Assigned</span><span className="font-bold text-purple-600">{stats.my_assigned || 0}</span></div>
            <div className="flex justify-between text-slate-500"><span>Closed Today</span><span className="font-bold text-green-600">{stats.closed_today || 0}</span></div>
          </div>
        </div>

        {/* ═══ MIDDLE: Thread List ═══ */}
        <div className="w-80 flex-shrink-0 border-r border-slate-200 bg-white flex flex-col">
          {/* Mailbox header */}
          <div className="px-3 py-2.5 border-b border-slate-100 bg-white">
            <div className="flex items-center justify-between mb-2">
              <h2 className="text-sm font-bold text-slate-800">{mailboxLabel(activeMailbox)}</h2>
              <button onClick={() => { loadThreads(); loadStats(); loadMailboxes(); }} className="text-slate-400 hover:text-slate-600"><RefreshCw size={14} /></button>
            </div>
            <div className="flex items-center gap-1.5 bg-slate-100 rounded-lg px-2 py-1">
              <Search size={13} className="text-slate-400" />
              <input value={searchQuery} onChange={e => setSearchQuery(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && loadThreads()}
                placeholder="Search..." className="flex-1 bg-transparent text-xs outline-none text-slate-700 placeholder:text-slate-400" />
              {searchQuery && <button onClick={() => { setSearchQuery(''); }} className="text-slate-400"><X size={12} /></button>}
            </div>
          </div>

          {/* Status filters */}
          <div className="px-3 py-1.5 border-b border-slate-100 flex gap-1 flex-wrap">
            {['', 'open', 'assigned', 'snoozed', 'closed'].map(s => (
              <button key={s} onClick={() => { setFilterStatus(s); setPage(1); }}
                className={`px-2 py-0.5 rounded text-[10px] font-semibold transition-colors ${
                  filterStatus === s ? 'bg-blue-100 text-blue-700' : 'bg-slate-50 text-slate-500 hover:bg-slate-100'
                }`}>{s || 'All'}</button>
            ))}
          </div>

          {/* Thread list */}
          <div className="flex-1 overflow-y-auto">
            {loading ? (
              <div className="flex items-center justify-center py-12"><Loader2 size={20} className="animate-spin text-slate-400" /></div>
            ) : threads.length === 0 ? (
              <div className="text-center py-12 text-slate-400 text-sm">
                <Mail size={28} className="mx-auto mb-2 opacity-40" />
                No emails in {mailboxLabel(activeMailbox)}
              </div>
            ) : threads.map(t => (
              <button key={t.id} onClick={() => openThread(t)}
                className={`w-full text-left px-3 py-2.5 border-b border-slate-100 hover:bg-slate-50 transition-colors ${
                  activeThread?.id === t.id ? 'bg-blue-50 border-l-2 border-l-blue-500' : ''
                } ${t.is_unread ? 'bg-white' : 'bg-slate-50/50'}`}>
                <div className="flex items-start gap-2.5">
                  <div className="h-7 w-7 rounded-full flex items-center justify-center text-[9px] font-bold text-white flex-shrink-0 mt-0.5"
                    style={{ background: initColor(t.from_name || t.from_email) }}>
                    {getInitials(t.from_name || t.from_email)}
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center justify-between">
                      <span className={`text-xs truncate ${t.is_unread ? 'font-bold text-slate-900' : 'font-medium text-slate-700'}`}>
                        {t.from_name || t.from_email}
                      </span>
                      <span className="text-[9px] text-slate-400 flex-shrink-0 ml-1">{formatTime(t.last_message_at)}</span>
                    </div>
                    <div className={`text-[11px] truncate mt-0.5 ${t.is_unread ? 'font-semibold text-slate-800' : 'text-slate-600'}`}>
                      {t.subject}
                    </div>
                    <div className="text-[10px] text-slate-400 truncate mt-0.5">{t.preview}</div>
                    <div className="flex items-center gap-1 mt-1 flex-wrap">
                      {t.tags?.map((tag: string) => (
                        <span key={tag} className="text-[8px] px-1 py-0 rounded bg-slate-100 text-slate-500 font-semibold">{tag}</span>
                      ))}
                      {t.assigned_to_name && (
                        <span className="text-[8px] px-1 py-0 rounded bg-purple-50 text-purple-600 font-semibold">→ {t.assigned_to_name.split(' ')[0]}</span>
                      )}
                      {t.customer_name && (
                        <span className="text-[8px] px-1 py-0 rounded bg-green-50 text-green-600 font-semibold">🔗 {t.customer_name.split(' ')[0]}</span>
                      )}
                      {t.priority === 'urgent' && <span className="text-[8px] px-1 py-0 rounded bg-red-100 text-red-600 font-bold">URGENT</span>}
                    </div>
                  </div>
                </div>
              </button>
            ))}
          </div>
          {total > 30 && (
            <div className="px-3 py-1.5 border-t border-slate-100 flex justify-between items-center text-[10px] text-slate-400">
              <button disabled={page <= 1} onClick={() => setPage(p => p - 1)} className="disabled:opacity-30">← Prev</button>
              <span>Page {page}</span>
              <button disabled={threads.length < 30} onClick={() => setPage(p => p + 1)} className="disabled:opacity-30">Next →</button>
            </div>
          )}
        </div>

        {/* ═══ RIGHT: Thread Detail ═══ */}
        <div className="flex-1 flex flex-col bg-white min-w-0">
          {!activeThread ? (
            <div className="flex-1 flex flex-col items-center justify-center text-slate-400">
              <Mail size={48} className="opacity-20 mb-3" />
              <span className="text-lg font-medium">Select a conversation</span>
              <span className="text-sm mt-1">Choose an email thread from the list</span>
            </div>
          ) : (
            <>
              {/* Thread header */}
              <div className="px-5 py-3 border-b border-slate-100 bg-slate-50 flex-shrink-0">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3 flex-1 min-w-0">
                    <div className="min-w-0">
                      <h2 className="text-sm font-bold text-slate-900 truncate">{activeThread.subject}</h2>
                      <div className="flex items-center gap-2 text-[11px] text-slate-500">
                        <span>{activeThread.from_name || activeThread.from_email}</span>
                        <span>·</span>
                        <span>{activeThread.message_count} msgs</span>
                        {activeThread.customer_name && <><span>·</span><span className="text-green-600">🔗 {activeThread.customer_name}</span></>}
                        <span>·</span>
                        <span className="bg-slate-200 px-1.5 py-0 rounded text-[9px] font-semibold">{activeThread.mailbox}</span>
                      </div>
                    </div>
                  </div>
                  <div className="flex items-center gap-2 flex-shrink-0">
                    {(canAssignAnyone || isAdmin) && (
                      <select value={activeThread.assigned_to_id || ''} onChange={e => handleAssign(activeThread.id, e.target.value ? parseInt(e.target.value) : null)}
                        className="text-[11px] border border-slate-200 rounded-lg px-2 py-1 bg-white max-w-32">
                        <option value="">Unassigned</option>
                        {employees.map((e: any) => <option key={e.id} value={e.id}>{e.full_name}</option>)}
                      </select>
                    )}
                    {activeThread.status !== 'closed' ? (
                      <button onClick={() => handleStatus(activeThread.id, 'closed')}
                        className="flex items-center gap-1 text-[11px] text-green-600 hover:text-green-700 font-semibold px-2 py-1 rounded hover:bg-green-50">
                        <Archive size={12} /> Close
                      </button>
                    ) : (
                      <button onClick={() => handleStatus(activeThread.id, 'open')}
                        className="flex items-center gap-1 text-[11px] text-blue-600 hover:text-blue-700 font-semibold px-2 py-1 rounded hover:bg-blue-50">
                        <MailOpen size={12} /> Reopen
                      </button>
                    )}
                  </div>
                </div>
                {/* Tags */}
                <div className="flex items-center gap-1 mt-1.5">
                  {(activeThread.tags || []).map((tag: string) => (
                    <span key={tag} className="text-[9px] px-1.5 py-0.5 rounded-full bg-slate-200 text-slate-600 font-semibold cursor-pointer hover:bg-red-100 hover:text-red-600"
                      onClick={() => emailAPI.tag(activeThread.id, tag, 'remove').then(() => openThread(activeThread))} title="Click to remove">
                      {tag} ×
                    </span>
                  ))}
                  <select className="text-[9px] border border-dashed border-slate-300 rounded px-1 py-0.5 text-slate-400 bg-transparent"
                    value="" onChange={e => { if (e.target.value) emailAPI.tag(activeThread.id, e.target.value).then(() => openThread(activeThread)); }}>
                    <option value="">+ Tag</option>
                    {TAGS.filter(t => !(activeThread.tags || []).includes(t)).map(t => <option key={t} value={t}>{t}</option>)}
                  </select>
                </div>
              </div>

              {/* Main content area — messages + AI panel */}
              <div className="flex-1 flex min-h-0">
                {/* Messages column */}
                <div className="flex-1 flex flex-col min-w-0">
                  <div className="flex-1 overflow-y-auto px-5 py-3 space-y-3">
                    {threadLoading ? (
                      <div className="flex items-center justify-center py-12"><Loader2 size={20} className="animate-spin text-slate-400" /></div>
                    ) : messages.map((msg) => (
                      <div key={msg.id} className={`rounded-xl border p-3 ${
                        msg.direction === 'inbound' ? 'bg-white border-slate-200' : 'bg-blue-50 border-blue-200 ml-6'
                      }`}>
                        <div className="flex items-center justify-between mb-1.5">
                          <div className="flex items-center gap-2">
                            <div className="h-6 w-6 rounded-full flex items-center justify-center text-[8px] font-bold text-white"
                              style={{ background: initColor(msg.from_name || msg.from_email) }}>
                              {getInitials(msg.from_name || msg.from_email)}
                            </div>
                            <div>
                              <span className="text-xs font-semibold text-slate-800">{msg.from_name || msg.from_email}</span>
                              <span className="text-[9px] text-slate-400 ml-1.5">&lt;{msg.from_email}&gt;</span>
                            </div>
                          </div>
                          <span className="text-[9px] text-slate-400">{formatTime(msg.created_at)}</span>
                        </div>
                        {msg.to_emails?.length > 0 && (
                          <div className="text-[9px] text-slate-400 mb-1.5">
                            To: {msg.to_emails.join(', ')}
                            {msg.cc_emails?.length > 0 && <> · CC: {msg.cc_emails.join(', ')}</>}
                          </div>
                        )}
                        <div className="text-[13px] text-slate-700 whitespace-pre-wrap leading-relaxed">
                          {msg.body_text || '(No text content)'}
                        </div>
                        {msg.attachments?.length > 0 && (
                          <div className="mt-2 flex gap-1.5 flex-wrap">
                            {msg.attachments.map((att: any, ai: number) => (
                              <a key={ai} href={`${process.env.NEXT_PUBLIC_API_URL || 'https://better-choice-api.onrender.com'}${att.path}`}
                                target="_blank" rel="noopener noreferrer"
                                className="flex items-center gap-1 px-1.5 py-0.5 rounded bg-slate-100 hover:bg-slate-200 text-[10px] text-slate-600">
                                <Paperclip size={10} /> {att.filename}
                              </a>
                            ))}
                          </div>
                        )}
                      </div>
                    ))}
                    <div ref={messagesEndRef} />
                  </div>

                  {/* Reply bar */}
                  <div className="border-t border-slate-200 bg-slate-50 flex-shrink-0">
                    {!replyOpen ? (
                      <div className="px-5 py-2.5 flex items-center gap-2">
                        <button onClick={() => setReplyOpen(true)}
                          className="flex items-center gap-1.5 px-3 py-1.5 bg-blue-600 hover:bg-blue-700 text-white text-xs font-semibold rounded-lg transition-colors">
                          <Send size={12} /> Reply
                        </button>
                        <button onClick={handleAiDraft} disabled={aiLoading}
                          className="flex items-center gap-1.5 px-3 py-1.5 bg-purple-50 hover:bg-purple-100 text-purple-700 text-xs font-semibold rounded-lg border border-purple-200 transition-colors disabled:opacity-50">
                          {aiLoading ? <Loader2 size={12} className="animate-spin" /> : <Sparkles size={12} />}
                          {aiLoading ? 'Analyzing...' : 'AI Assist'}
                        </button>
                        {activeThread.status !== 'closed' && (
                          <button onClick={() => handleStatus(activeThread.id, 'closed')}
                            className="flex items-center gap-1 text-[10px] text-slate-500 hover:text-green-600 ml-auto">
                            <Archive size={12} /> Close
                          </button>
                        )}
                      </div>
                    ) : (
                      <div className="px-5 py-2.5 space-y-2">
                        {aiDraft && (
                          <div className="text-[10px] text-purple-600 font-semibold flex items-center gap-1">
                            <Sparkles size={10} /> AI-generated draft — edit before sending
                          </div>
                        )}
                        <div className="flex gap-2 mb-1">
                          <button onClick={() => setReplySendAs('service')}
                            className={`px-2.5 py-1 rounded text-[10px] font-semibold border transition-colors ${
                              replySendAs === 'service' ? 'bg-blue-50 border-blue-300 text-blue-700' : 'bg-white border-slate-200 text-slate-500'
                            }`}>service@</button>
                          <button onClick={() => setReplySendAs('personal')}
                            className={`px-2.5 py-1 rounded text-[10px] font-semibold border transition-colors ${
                              replySendAs === 'personal' ? 'bg-blue-50 border-blue-300 text-blue-700' : 'bg-white border-slate-200 text-slate-500'
                            }`}>My Email</button>
                        </div>
                        <input value={replyCc} onChange={e => setReplyCc(e.target.value)} placeholder="CC (comma-separated)"
                          className="w-full border border-slate-200 rounded-lg px-2.5 py-1 text-[11px]" />
                        <textarea value={replyBody} onChange={e => setReplyBody(e.target.value)} rows={4} autoFocus
                          placeholder="Type your reply..."
                          className="w-full border border-slate-200 rounded-lg px-2.5 py-2 text-xs resize-none focus:ring-2 focus:ring-blue-500 outline-none" />
                        <div className="flex items-center justify-between">
                          <div className="flex items-center gap-2">
                            <input ref={replyFileRef} type="file" multiple className="hidden"
                              onChange={e => { if (e.target.files) setReplyFiles(prev => [...prev, ...Array.from(e.target.files!)]); e.target.value = ''; }} />
                            <button onClick={() => replyFileRef.current?.click()} className="text-[10px] text-slate-500 hover:text-slate-700 flex items-center gap-1">
                              <Paperclip size={11} /> Attach
                            </button>
                            {replyFiles.map((f, i) => (
                              <span key={i} className="text-[9px] bg-slate-100 rounded px-1 py-0.5 text-slate-500">
                                {f.name} <button onClick={() => setReplyFiles(prev => prev.filter((_, j) => j !== i))} className="text-red-400 ml-0.5">×</button>
                              </span>
                            ))}
                            <label className="flex items-center gap-1 text-[9px] text-slate-400 cursor-pointer">
                              <input type="checkbox" checked={closeAfterReply} onChange={e => setCloseAfterReply(e.target.checked)} className="rounded" />
                              Close after
                            </label>
                          </div>
                          <div className="flex items-center gap-2">
                            <button onClick={() => { setReplyOpen(false); }} className="text-[10px] text-slate-500">Cancel</button>
                            <button disabled={!replyBody.trim() || replySending} onClick={handleReply}
                              className="flex items-center gap-1 px-3 py-1 bg-blue-600 hover:bg-blue-700 text-white text-[11px] font-semibold rounded-lg disabled:opacity-40 transition-colors">
                              {replySending ? <Loader2 size={11} className="animate-spin" /> : <Send size={11} />}
                              {replySending ? 'Sending...' : 'Send'}
                            </button>
                          </div>
                        </div>
                      </div>
                    )}
                  </div>
                </div>

                {/* ═══ AI PANEL (right side) ═══ */}
                {(aiActionItems.length > 0 || aiSummary || aiLoading) && (
                  <div className="w-72 flex-shrink-0 border-l border-slate-200 bg-slate-50 overflow-y-auto">
                    <div className="p-4">
                      <div className="flex items-center justify-between mb-3">
                        <div className="flex items-center gap-1.5">
                          <Sparkles size={14} className="text-purple-500" />
                          <h3 className="text-xs font-bold text-slate-700">AI Analysis</h3>
                        </div>
                        <button onClick={() => { setAiActionItems([]); setAiSummary(''); setAiUrgency('normal'); }}
                          className="text-slate-400 hover:text-slate-600"><X size={12} /></button>
                      </div>

                      {aiLoading ? (
                        <div className="flex items-center gap-2 text-xs text-slate-400 py-6 justify-center">
                          <Loader2 size={14} className="animate-spin" /> Analyzing email...
                        </div>
                      ) : (
                        <>
                          {/* Summary */}
                          {aiSummary && (
                            <div className="mb-4">
                              <div className="text-[10px] font-bold text-slate-400 uppercase tracking-wider mb-1">Summary</div>
                              <p className="text-xs text-slate-700 bg-white rounded-lg p-2.5 border border-slate-200 leading-relaxed">{aiSummary}</p>
                            </div>
                          )}

                          {/* Urgency */}
                          {aiUrgency && aiUrgency !== 'normal' && (
                            <div className="mb-4">
                              <div className="text-[10px] font-bold text-slate-400 uppercase tracking-wider mb-1">Urgency</div>
                              <div className={`flex items-center gap-1.5 text-xs font-semibold ${urgencyColor[aiUrgency] || 'text-slate-500'}`}>
                                {aiUrgency === 'urgent' && <AlertTriangle size={13} />}
                                {aiUrgency === 'high' && <AlertCircle size={13} />}
                                <span className="capitalize">{aiUrgency}</span>
                              </div>
                            </div>
                          )}

                          {/* Action Items */}
                          {aiActionItems.length > 0 && (
                            <div className="mb-4">
                              <div className="text-[10px] font-bold text-slate-400 uppercase tracking-wider mb-1.5 flex items-center gap-1">
                                <ListChecks size={11} /> Next Steps
                              </div>
                              <div className="space-y-1.5">
                                {aiActionItems.map((item, i) => (
                                  <div key={i} className="flex items-start gap-2 bg-white rounded-lg p-2 border border-slate-200">
                                    <div className="w-4 h-4 rounded-full bg-purple-100 flex items-center justify-center flex-shrink-0 mt-0.5">
                                      <span className="text-[8px] font-bold text-purple-600">{i + 1}</span>
                                    </div>
                                    <span className="text-[11px] text-slate-700 leading-relaxed">{item}</span>
                                  </div>
                                ))}
                              </div>
                            </div>
                          )}

                          {/* Regenerate */}
                          <button onClick={handleAiDraft} disabled={aiLoading}
                            className="w-full text-center text-[10px] text-purple-500 hover:text-purple-700 py-1">
                            <RefreshCw size={10} className="inline mr-1" /> Regenerate analysis
                          </button>
                        </>
                      )}
                    </div>
                  </div>
                )}
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
