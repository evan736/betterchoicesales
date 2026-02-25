import React, { useState, useEffect, useRef, useCallback } from 'react';
import { emailAPI } from '../lib/api';
import { useAuth } from '../contexts/AuthContext';
import { useEmail } from '../contexts/EmailContext';
import { useChat } from '../contexts/ChatContext';
import {
  Mail, Search, Inbox, Send, User, Clock, Loader2, X, CheckCircle2,
  Paperclip, Sparkles, Archive, RefreshCw, MailOpen, ChevronLeft,
  PanelRightClose, AlertCircle, AlertTriangle, ListChecks,
} from 'lucide-react';

const TAGS = ['billing', 'claims', 'new-business', 'endorsement', 'renewal', 'general', 'urgent'];

export default function EmailPanel() {
  const { user } = useAuth();
  const { sidebarOpen: open, openSidebar, closeSidebar, unreadCount, openCount, unassignedCount, refreshStats } = useEmail();
  const { sidebarOpen: chatOpen } = useChat();

  // Mailboxes
  const [mailboxes, setMailboxes] = useState<any[]>([]);
  const [activeMailbox, setActiveMailbox] = useState('service');
  const [isAdmin, setIsAdmin] = useState(false);
  const [canAssignAnyone, setCanAssignAnyone] = useState(false);

  // Threads
  const [threads, setThreads] = useState<any[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [filterStatus, setFilterStatus] = useState('');

  // Active thread
  const [activeThread, setActiveThread] = useState<any>(null);
  const [messages, setMessages] = useState<any[]>([]);
  const [threadLoading, setThreadLoading] = useState(false);
  const [employees, setEmployees] = useState<any[]>([]);

  // Reply
  const [replyOpen, setReplyOpen] = useState(false);
  const [replyBody, setReplyBody] = useState('');
  const [replyCc, setReplyCc] = useState('');
  const [replySendAs, setReplySendAs] = useState<'service' | 'personal'>('service');
  const [replyFiles, setReplyFiles] = useState<File[]>([]);
  const [replySending, setReplySending] = useState(false);
  const [closeAfterReply, setCloseAfterReply] = useState(false);
  const replyFileRef = useRef<HTMLInputElement>(null);

  // AI
  const [aiDraft, setAiDraft] = useState('');
  const [aiActionItems, setAiActionItems] = useState<string[]>([]);
  const [aiUrgency, setAiUrgency] = useState('normal');
  const [aiSummary, setAiSummary] = useState('');
  const [aiLoading, setAiLoading] = useState(false);
  const [showAiPanel, setShowAiPanel] = useState(false);

  // View state
  const [view, setView] = useState<'inbox' | 'thread'>('inbox');
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const loadMailboxes = async () => {
    try {
      const res = await emailAPI.mailboxes();
      setMailboxes(res.data.mailboxes);
      setIsAdmin(res.data.is_admin);
      setCanAssignAnyone(res.data.can_assign_anyone);
    } catch {}
  };

  const loadThreads = useCallback(async () => {
    setLoading(true);
    try {
      const params: any = { page: 1, page_size: 25, mailbox: activeMailbox };
      if (filterStatus) params.status = filterStatus;
      if (searchQuery) params.search = searchQuery;
      const res = await emailAPI.threads(params);
      setThreads(res.data.threads);
      setTotal(res.data.total);
    } catch {}
    finally { setLoading(false); }
  }, [activeMailbox, filterStatus, searchQuery]);

  const loadEmployees = async () => {
    try {
      const { chatAPI } = await import('../lib/api');
      const res = await chatAPI.listUsers();
      setEmployees(res.data);
    } catch {}
  };

  useEffect(() => {
    if (open) { loadMailboxes(); loadThreads(); loadEmployees(); }
  }, [open, loadThreads]);

  const openThread = async (thread: any) => {
    setActiveThread(thread);
    setView('thread');
    setReplyOpen(false);
    setAiDraft(''); setAiActionItems([]); setAiSummary(''); setShowAiPanel(false);
    setThreadLoading(true);
    try {
      const res = await emailAPI.thread(thread.id);
      setActiveThread(res.data.thread);
      setMessages(res.data.messages);
      setThreads(prev => prev.map(t => t.id === thread.id ? { ...t, is_unread: false } : t));
      refreshStats();
    } catch {}
    finally { setThreadLoading(false); }
  };

  const handleReply = async () => {
    if (!activeThread || !replyBody.trim()) return;
    setReplySending(true);
    try {
      await emailAPI.reply(activeThread.id, {
        body: replyBody, cc_emails: replyCc || undefined,
        send_as: replySendAs, close_after: closeAfterReply,
        attachments: replyFiles.length > 0 ? replyFiles : undefined,
      });
      setReplyBody(''); setReplyCc(''); setReplyFiles([]); setReplyOpen(false);
      if (closeAfterReply) { setView('inbox'); setActiveThread(null); }
      else { openThread(activeThread); }
      loadThreads(); refreshStats();
    } catch (e: any) { alert(e.response?.data?.detail || 'Failed to send'); }
    finally { setReplySending(false); }
  };

  const handleAiDraft = async () => {
    if (!activeThread) return;
    setAiLoading(true); setShowAiPanel(true);
    try {
      const res = await emailAPI.aiDraft(activeThread.id);
      setAiDraft(res.data.draft);
      setAiActionItems(res.data.action_items || []);
      setAiUrgency(res.data.urgency || 'normal');
      setAiSummary(res.data.summary || '');
      setReplyBody(res.data.draft);
      setReplyOpen(true);
    } catch (e: any) { alert(e.response?.data?.detail || 'AI failed'); }
    finally { setAiLoading(false); }
  };

  const handleAssign = async (threadId: number, userId: number | null) => {
    try { await emailAPI.assign(threadId, userId); openThread(activeThread); loadThreads(); } catch {}
  };

  const handleStatus = async (threadId: number, status: string) => {
    try {
      await emailAPI.setStatus(threadId, status);
      if (status === 'closed') { setView('inbox'); setActiveThread(null); }
      loadThreads(); refreshStats();
    } catch {}
  };

  // Helpers
  const formatTime = (iso: string) => {
    if (!iso) return '';
    const d = new Date(iso);
    const diffMs = Date.now() - d.getTime();
    if (diffMs < 60000) return 'now';
    if (diffMs < 3600000) return `${Math.floor(diffMs / 60000)}m`;
    if (diffMs < 86400000) return d.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' });
    return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
  };
  const getInitials = (n: string) => n?.split(' ').map(w => w[0]).join('').slice(0, 2).toUpperCase() || '?';
  const initColor = (n: string) => {
    const c = ['#06b6d4','#8b5cf6','#f59e0b','#10b981','#ef4444','#ec4899','#6366f1','#14b8a6'];
    let h = 0; for (let i = 0; i < (n||'').length; i++) h = n.charCodeAt(i) + ((h << 5) - h);
    return c[Math.abs(h) % c.length];
  };
  const mailboxLabel = (mb: string) => mb === 'service' ? 'Service' : mb.split('.').map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' ');

  // Position: offset by chat sidebar width
  const rightOffset = chatOpen ? 380 : 48;

  if (!user) return null;

  // ═══ COLLAPSED STATE ═══
  if (!open) {
    return (
      <div className="fixed top-0 h-full w-12 z-40 bg-[#0a1628]/80 border-l border-cyan-900/20 flex flex-col items-center pt-20 gap-4"
        style={{ right: `${rightOffset}px`, backdropFilter: 'blur(10px)' }}>
        <button onClick={() => { openSidebar(); loadMailboxes(); loadThreads(); }}
          className="relative h-10 w-10 rounded-lg bg-blue-500/15 text-blue-400 hover:bg-blue-500/25 flex items-center justify-center transition-colors"
          title="Open Email Inbox">
          <Mail size={20} />
          {unreadCount > 0 && (
            <span className="absolute -top-1 -right-1 h-4 min-w-[16px] px-1 rounded-full bg-red-500 text-white text-[9px] font-bold flex items-center justify-center animate-pulse">
              {unreadCount > 99 ? '99+' : unreadCount}
            </span>
          )}
        </button>
        {/* Quick stats dots */}
        {openCount > 0 && (
          <div className="flex flex-col items-center gap-1">
            <span className="text-[8px] text-blue-400 font-bold">{openCount}</span>
            <span className="text-[7px] text-slate-500">open</span>
          </div>
        )}
      </div>
    );
  }

  // ═══ EXPANDED STATE ═══
  return (
    <div className="fixed top-0 h-full w-[380px] z-40 flex flex-col bg-[#0a1628] border-l border-blue-900/30 shadow-2xl shadow-black/40"
      style={{ right: `${rightOffset}px`, backdropFilter: 'blur(20px)' }}>

      {/* ─── HEADER ─── */}
      <div className="flex items-center justify-between px-3 py-2.5 bg-gradient-to-r from-[#0d1f3c] to-[#0a1628] border-b border-blue-900/20">
        {view === 'thread' && activeThread ? (
          <>
            <button onClick={() => { setView('inbox'); setActiveThread(null); setShowAiPanel(false); }} className="text-slate-400 hover:text-white mr-2">
              <ChevronLeft size={18} />
            </button>
            <div className="flex-1 min-w-0">
              <h3 className="text-xs font-bold text-white truncate">{activeThread.subject}</h3>
              <span className="text-[10px] text-slate-400">{activeThread.from_name || activeThread.from_email}</span>
            </div>
          </>
        ) : (
          <>
            <div className="flex items-center gap-2">
              <Mail size={16} className="text-blue-400" />
              <h3 className="text-sm font-bold text-white">Inbox</h3>
              {unreadCount > 0 && <span className="text-[9px] bg-red-500 text-white px-1.5 py-0.5 rounded-full font-bold">{unreadCount}</span>}
            </div>
          </>
        )}
        <div className="flex items-center gap-1">
          <button onClick={() => { loadThreads(); refreshStats(); }} className="text-slate-500 hover:text-white p-1"><RefreshCw size={14} /></button>
          <button onClick={closeSidebar} className="text-slate-500 hover:text-white p-1"><PanelRightClose size={16} /></button>
        </div>
      </div>

      {/* ─── INBOX VIEW ─── */}
      {view === 'inbox' && (
        <>
          {/* Mailbox tabs */}
          <div className="px-2 py-1.5 border-b border-white/[0.06] flex gap-1 overflow-x-auto">
            {mailboxes.map(mb => (
              <button key={mb.mailbox} onClick={() => setActiveMailbox(mb.mailbox)}
                className={`flex items-center gap-1 px-2 py-1 rounded text-[10px] font-semibold whitespace-nowrap transition-colors ${
                  activeMailbox === mb.mailbox
                    ? 'bg-blue-500/20 text-blue-300'
                    : 'text-slate-500 hover:text-slate-300 hover:bg-white/[0.04]'
                }`}>
                {mb.mailbox === 'service' ? <Inbox size={11} /> : <User size={11} />}
                {mailboxLabel(mb.mailbox)}
                {mb.open_count > 0 && (
                  <span className={`text-[8px] px-1 rounded-full ${
                    activeMailbox === mb.mailbox ? 'bg-blue-400/30 text-blue-200' : 'bg-white/10 text-slate-400'
                  }`}>{mb.open_count}</span>
                )}
              </button>
            ))}
          </div>

          {/* Search */}
          <div className="px-2 py-1.5 border-b border-white/[0.06]">
            <div className="flex items-center gap-1.5 bg-white/[0.06] rounded-lg px-2 py-1">
              <Search size={12} className="text-slate-500" />
              <input value={searchQuery} onChange={e => setSearchQuery(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && loadThreads()}
                placeholder="Search emails..."
                className="flex-1 bg-transparent text-[11px] outline-none text-white placeholder:text-slate-600" />
              {searchQuery && <button onClick={() => setSearchQuery('')} className="text-slate-500"><X size={10} /></button>}
            </div>
            <div className="flex gap-1 mt-1">
              {['', 'open', 'assigned', 'closed'].map(s => (
                <button key={s} onClick={() => setFilterStatus(s)}
                  className={`px-1.5 py-0.5 rounded text-[8px] font-semibold transition-colors ${
                    filterStatus === s ? 'bg-blue-500/20 text-blue-300' : 'text-slate-600 hover:text-slate-400'
                  }`}>{s || 'All'}</button>
              ))}
            </div>
          </div>

          {/* Thread list */}
          <div className="flex-1 overflow-y-auto">
            {loading ? (
              <div className="flex justify-center py-8"><Loader2 size={16} className="animate-spin text-slate-500" /></div>
            ) : threads.length === 0 ? (
              <div className="text-center py-8 text-slate-600 text-xs">
                <Mail size={24} className="mx-auto mb-2 opacity-30" />
                No emails
              </div>
            ) : threads.map(t => (
              <button key={t.id} onClick={() => openThread(t)}
                className={`w-full text-left px-3 py-2 border-b border-white/[0.04] hover:bg-white/[0.03] transition-colors ${
                  t.is_unread ? 'bg-blue-500/[0.05]' : ''
                }`}>
                <div className="flex items-start gap-2">
                  <div className="h-6 w-6 rounded-full flex items-center justify-center text-[8px] font-bold text-white flex-shrink-0 mt-0.5"
                    style={{ background: initColor(t.from_name || t.from_email) }}>
                    {getInitials(t.from_name || t.from_email)}
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center justify-between">
                      <span className={`text-[11px] truncate ${t.is_unread ? 'font-bold text-white' : 'font-medium text-slate-300'}`}>
                        {t.from_name || t.from_email}
                      </span>
                      <span className="text-[8px] text-slate-600 ml-1">{formatTime(t.last_message_at)}</span>
                    </div>
                    <div className={`text-[10px] truncate ${t.is_unread ? 'font-semibold text-slate-200' : 'text-slate-400'}`}>
                      {t.subject}
                    </div>
                    <div className="text-[9px] text-slate-600 truncate">{t.preview}</div>
                    <div className="flex items-center gap-1 mt-0.5">
                      {t.tags?.slice(0, 2).map((tag: string) => (
                        <span key={tag} className="text-[7px] px-1 rounded bg-white/[0.06] text-slate-500">{tag}</span>
                      ))}
                      {t.assigned_to_name && <span className="text-[7px] px-1 rounded bg-purple-500/10 text-purple-400">→ {t.assigned_to_name.split(' ')[0]}</span>}
                      {t.priority === 'urgent' && <span className="text-[7px] px-1 rounded bg-red-500/20 text-red-400">URGENT</span>}
                    </div>
                  </div>
                </div>
              </button>
            ))}
          </div>

          {/* Bottom stats */}
          <div className="px-3 py-2 border-t border-white/[0.06] flex justify-between text-[9px] text-slate-600">
            <span>{openCount} open</span>
            <span>{unassignedCount} unassigned</span>
            <span>{total} total</span>
          </div>
        </>
      )}

      {/* ─── THREAD VIEW ─── */}
      {view === 'thread' && activeThread && (
        <>
          {/* Thread meta */}
          <div className="px-3 py-2 border-b border-white/[0.06] flex items-center justify-between">
            <div className="flex items-center gap-1.5 flex-1 min-w-0">
              {activeThread.customer_name && <span className="text-[9px] text-green-400">🔗 {activeThread.customer_name}</span>}
              <span className="text-[9px] bg-white/[0.06] text-slate-500 px-1 rounded">{activeThread.mailbox}</span>
              {activeThread.message_count > 1 && <span className="text-[9px] text-slate-600">{activeThread.message_count} msgs</span>}
            </div>
            <div className="flex items-center gap-1">
              {(canAssignAnyone || isAdmin) && (
                <select value={activeThread.assigned_to_id || ''} onChange={e => handleAssign(activeThread.id, e.target.value ? parseInt(e.target.value) : null)}
                  className="text-[9px] bg-white/[0.06] border border-white/[0.08] rounded px-1 py-0.5 text-slate-300 max-w-24">
                  <option value="">Assign</option>
                  {employees.map((e: any) => <option key={e.id} value={e.id}>{e.full_name}</option>)}
                </select>
              )}
              {activeThread.status !== 'closed' ? (
                <button onClick={() => handleStatus(activeThread.id, 'closed')} className="text-[9px] text-green-400 hover:text-green-300 px-1">
                  <Archive size={12} />
                </button>
              ) : (
                <button onClick={() => handleStatus(activeThread.id, 'open')} className="text-[9px] text-blue-400 hover:text-blue-300 px-1">
                  <MailOpen size={12} />
                </button>
              )}
            </div>
          </div>

          {/* Tags */}
          <div className="px-3 py-1 border-b border-white/[0.04] flex items-center gap-1 flex-wrap">
            {(activeThread.tags || []).map((tag: string) => (
              <span key={tag} className="text-[8px] px-1.5 py-0.5 rounded-full bg-white/[0.06] text-slate-400 cursor-pointer hover:bg-red-500/20 hover:text-red-400"
                onClick={() => emailAPI.tag(activeThread.id, tag, 'remove').then(() => openThread(activeThread))}>
                {tag} ×
              </span>
            ))}
            <select className="text-[8px] bg-transparent border border-dashed border-white/10 rounded px-0.5 text-slate-600"
              value="" onChange={e => { if (e.target.value) emailAPI.tag(activeThread.id, e.target.value).then(() => openThread(activeThread)); }}>
              <option value="">+</option>
              {TAGS.filter(t => !(activeThread.tags || []).includes(t)).map(t => <option key={t} value={t}>{t}</option>)}
            </select>
          </div>

          {/* AI Panel (collapsible) */}
          {showAiPanel && (aiActionItems.length > 0 || aiSummary || aiLoading) && (
            <div className="px-3 py-2 border-b border-purple-500/20 bg-purple-500/[0.05] max-h-48 overflow-y-auto">
              <div className="flex items-center justify-between mb-1.5">
                <div className="flex items-center gap-1"><Sparkles size={11} className="text-purple-400" /><span className="text-[10px] font-bold text-purple-300">AI Analysis</span></div>
                <button onClick={() => setShowAiPanel(false)} className="text-slate-600 hover:text-slate-400"><X size={10} /></button>
              </div>
              {aiLoading ? (
                <div className="flex items-center gap-1.5 text-[10px] text-slate-500 py-2"><Loader2 size={12} className="animate-spin" /> Analyzing...</div>
              ) : (
                <>
                  {aiSummary && <p className="text-[10px] text-slate-300 bg-white/[0.04] rounded p-1.5 mb-1.5 leading-relaxed">{aiSummary}</p>}
                  {aiUrgency && aiUrgency !== 'normal' && (
                    <div className={`text-[10px] font-semibold mb-1.5 flex items-center gap-1 ${
                      aiUrgency === 'urgent' ? 'text-red-400' : aiUrgency === 'high' ? 'text-amber-400' : 'text-slate-400'
                    }`}>
                      {aiUrgency === 'urgent' ? <AlertTriangle size={10} /> : <AlertCircle size={10} />}
                      <span className="capitalize">{aiUrgency} priority</span>
                    </div>
                  )}
                  {aiActionItems.length > 0 && (
                    <div className="space-y-1">
                      <div className="text-[9px] font-bold text-slate-500 uppercase tracking-wider flex items-center gap-1"><ListChecks size={9} /> Next Steps</div>
                      {aiActionItems.map((item, i) => (
                        <div key={i} className="flex items-start gap-1.5 text-[10px] text-slate-300">
                          <span className="text-[8px] font-bold text-purple-400 bg-purple-500/20 rounded-full w-3.5 h-3.5 flex items-center justify-center flex-shrink-0 mt-0.5">{i+1}</span>
                          <span className="leading-relaxed">{item}</span>
                        </div>
                      ))}
                    </div>
                  )}
                </>
              )}
            </div>
          )}

          {/* Messages */}
          <div className="flex-1 overflow-y-auto px-3 py-2 space-y-2">
            {threadLoading ? (
              <div className="flex justify-center py-8"><Loader2 size={16} className="animate-spin text-slate-500" /></div>
            ) : messages.map(msg => (
              <div key={msg.id} className={`rounded-lg border p-2.5 ${
                msg.direction === 'inbound'
                  ? 'bg-white/[0.03] border-white/[0.06]'
                  : 'bg-blue-500/[0.06] border-blue-500/20 ml-4'
              }`}>
                <div className="flex items-center justify-between mb-1">
                  <div className="flex items-center gap-1.5">
                    <div className="h-5 w-5 rounded-full flex items-center justify-center text-[7px] font-bold text-white"
                      style={{ background: initColor(msg.from_name || msg.from_email) }}>
                      {getInitials(msg.from_name || msg.from_email)}
                    </div>
                    <span className="text-[10px] font-semibold text-slate-200">{msg.from_name || msg.from_email}</span>
                  </div>
                  <span className="text-[8px] text-slate-600">{formatTime(msg.created_at)}</span>
                </div>
                <div className="text-[11px] text-slate-300 whitespace-pre-wrap leading-relaxed">
                  {msg.body_text || '(No content)'}
                </div>
                {msg.attachments?.length > 0 && (
                  <div className="mt-1.5 flex gap-1 flex-wrap">
                    {msg.attachments.map((att: any, ai: number) => (
                      <a key={ai} href={`${process.env.NEXT_PUBLIC_API_URL || 'https://better-choice-api.onrender.com'}${att.path}`}
                        target="_blank" rel="noopener noreferrer"
                        className="flex items-center gap-0.5 px-1 py-0.5 rounded bg-white/[0.06] text-[8px] text-slate-400 hover:text-blue-300">
                        <Paperclip size={8} /> {att.filename}
                      </a>
                    ))}
                  </div>
                )}
              </div>
            ))}
            <div ref={messagesEndRef} />
          </div>

          {/* Reply area */}
          <div className="border-t border-white/[0.06] bg-[#0d1f3c]/50">
            {!replyOpen ? (
              <div className="px-3 py-2 flex items-center gap-1.5">
                <button onClick={() => setReplyOpen(true)}
                  className="flex items-center gap-1 px-2.5 py-1 bg-blue-600 hover:bg-blue-700 text-white text-[10px] font-semibold rounded-lg transition-colors">
                  <Send size={10} /> Reply
                </button>
                <button onClick={handleAiDraft} disabled={aiLoading}
                  className="flex items-center gap-1 px-2.5 py-1 bg-purple-500/15 hover:bg-purple-500/25 text-purple-300 text-[10px] font-semibold rounded-lg border border-purple-500/20 transition-colors disabled:opacity-50">
                  {aiLoading ? <Loader2 size={10} className="animate-spin" /> : <Sparkles size={10} />}
                  AI Assist
                </button>
                {activeThread.status !== 'closed' && (
                  <button onClick={() => handleStatus(activeThread.id, 'closed')} className="text-[9px] text-slate-600 hover:text-green-400 ml-auto" title="Close">
                    <Archive size={12} />
                  </button>
                )}
              </div>
            ) : (
              <div className="px-3 py-2 space-y-1.5">
                {aiDraft && <div className="text-[8px] text-purple-400 font-semibold flex items-center gap-1"><Sparkles size={8} /> AI draft — edit before sending</div>}
                <div className="flex gap-1.5">
                  <button onClick={() => setReplySendAs('service')}
                    className={`px-2 py-0.5 rounded text-[9px] font-semibold border transition-colors ${
                      replySendAs === 'service' ? 'bg-blue-500/20 border-blue-500/30 text-blue-300' : 'bg-white/[0.04] border-white/[0.08] text-slate-500'
                    }`}>service@</button>
                  <button onClick={() => setReplySendAs('personal')}
                    className={`px-2 py-0.5 rounded text-[9px] font-semibold border transition-colors ${
                      replySendAs === 'personal' ? 'bg-blue-500/20 border-blue-500/30 text-blue-300' : 'bg-white/[0.04] border-white/[0.08] text-slate-500'
                    }`}>My Email</button>
                </div>
                <input value={replyCc} onChange={e => setReplyCc(e.target.value)} placeholder="CC"
                  className="w-full bg-white/[0.04] border border-white/[0.08] rounded px-2 py-1 text-[10px] text-white placeholder:text-slate-600 outline-none" />
                <textarea value={replyBody} onChange={e => setReplyBody(e.target.value)} rows={3} autoFocus
                  placeholder="Type reply..."
                  className="w-full bg-white/[0.04] border border-white/[0.08] rounded px-2 py-1.5 text-[10px] text-white placeholder:text-slate-600 resize-none outline-none focus:border-blue-500/30" />
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-1.5">
                    <input ref={replyFileRef} type="file" multiple className="hidden"
                      onChange={e => { if (e.target.files) setReplyFiles(prev => [...prev, ...Array.from(e.target.files!)]); e.target.value = ''; }} />
                    <button onClick={() => replyFileRef.current?.click()} className="text-[9px] text-slate-600 hover:text-slate-400 flex items-center gap-0.5">
                      <Paperclip size={9} /> Attach
                    </button>
                    {replyFiles.map((f, i) => (
                      <span key={i} className="text-[8px] bg-white/[0.06] rounded px-1 text-slate-500">
                        {f.name.slice(0, 12)} <button onClick={() => setReplyFiles(prev => prev.filter((_, j) => j !== i))} className="text-red-400">×</button>
                      </span>
                    ))}
                    <label className="flex items-center gap-0.5 text-[8px] text-slate-600 cursor-pointer">
                      <input type="checkbox" checked={closeAfterReply} onChange={e => setCloseAfterReply(e.target.checked)} className="rounded w-2.5 h-2.5" />
                      Close
                    </label>
                  </div>
                  <div className="flex items-center gap-1.5">
                    <button onClick={() => setReplyOpen(false)} className="text-[9px] text-slate-600">Cancel</button>
                    <button disabled={!replyBody.trim() || replySending} onClick={handleReply}
                      className="flex items-center gap-1 px-2.5 py-1 bg-blue-600 hover:bg-blue-700 text-white text-[9px] font-semibold rounded-lg disabled:opacity-40 transition-colors">
                      {replySending ? <Loader2 size={9} className="animate-spin" /> : <Send size={9} />}
                      Send
                    </button>
                  </div>
                </div>
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}
