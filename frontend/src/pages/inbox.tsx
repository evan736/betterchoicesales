import React, { useEffect, useState, useRef, useCallback } from 'react';
import { useAuth } from '../contexts/AuthContext';
import Navbar from '../components/Navbar';
import { emailAPI } from '../lib/api';
import {
  Mail, Search, Inbox, Send, User, Clock, Tag, ChevronDown, ChevronRight,
  Loader2, X, CheckCircle2, AlertCircle, Paperclip, FileText, Sparkles,
  Archive, RefreshCw, ArrowLeft, MailOpen, Star, Users, Filter,
} from 'lucide-react';

const TAGS = ['billing', 'claims', 'new-business', 'endorsement', 'renewal', 'general', 'urgent'];
const PRIORITIES = ['low', 'normal', 'high', 'urgent'];

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

  // Filters
  const [filterMailbox, setFilterMailbox] = useState('');
  const [filterStatus, setFilterStatus] = useState('');
  const [filterAssigned, setFilterAssigned] = useState<number | undefined>(undefined);
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

  // AI Draft
  const [aiDraft, setAiDraft] = useState('');
  const [aiLoading, setAiLoading] = useState(false);

  const messagesEndRef = useRef<HTMLDivElement>(null);

  const loadThreads = useCallback(async () => {
    setLoading(true);
    try {
      const params: any = { page, page_size: 30 };
      if (filterMailbox) params.mailbox = filterMailbox;
      if (filterStatus) params.status = filterStatus;
      if (filterAssigned !== undefined) params.assigned_to = filterAssigned;
      if (searchQuery) params.search = searchQuery;
      const res = await emailAPI.threads(params);
      setThreads(res.data.threads);
      setTotal(res.data.total);
    } catch (e) { console.error(e); }
    finally { setLoading(false); }
  }, [page, filterMailbox, filterStatus, filterAssigned, searchQuery]);

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

  useEffect(() => { loadThreads(); loadStats(); loadEmployees(); }, [loadThreads]);

  const openThread = async (thread: any) => {
    setActiveThread(thread);
    setReplyOpen(false);
    setAiDraft('');
    setThreadLoading(true);
    try {
      const res = await emailAPI.thread(thread.id);
      setActiveThread(res.data.thread);
      setMessages(res.data.messages);
      // Mark as read in list
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
      setReplyBody('');
      setReplyCc('');
      setReplyFiles([]);
      setReplyOpen(false);
      if (closeAfterReply) {
        setActiveThread(null);
        loadThreads();
      } else {
        openThread(activeThread);
      }
      loadStats();
    } catch (e: any) {
      alert(e.response?.data?.detail || 'Failed to send');
    } finally { setReplySending(false); }
  };

  const handleAiDraft = async () => {
    if (!activeThread) return;
    setAiLoading(true);
    try {
      const res = await emailAPI.aiDraft(activeThread.id);
      setAiDraft(res.data.draft);
      setReplyBody(res.data.draft);
      setReplyOpen(true);
    } catch (e: any) {
      alert(e.response?.data?.detail || 'AI draft failed');
    } finally { setAiLoading(false); }
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
      loadThreads(); loadStats();
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

  if (!user) return null;

  return (
    <div className="min-h-screen bg-slate-50">
      <Navbar />
      <div className="flex" style={{ height: 'calc(100vh - 64px)' }}>

        {/* Left: Thread List */}
        <div className="w-96 flex-shrink-0 border-r border-slate-200 bg-white flex flex-col">
          {/* Stats bar */}
          <div className="px-4 py-3 border-b border-slate-100 bg-slate-50">
            <div className="flex items-center gap-3 text-xs">
              <span className="flex items-center gap-1 font-semibold text-blue-600"><Inbox size={13} />{stats.open || 0} Open</span>
              <span className="flex items-center gap-1 text-amber-600"><Clock size={13} />{stats.unassigned || 0} Unassigned</span>
              <span className="flex items-center gap-1 text-green-600"><CheckCircle2 size={13} />{stats.closed_today || 0} Closed</span>
              <span className="flex items-center gap-1 text-purple-600"><User size={13} />{stats.my_assigned || 0} Mine</span>
            </div>
          </div>

          {/* Search + Filters */}
          <div className="px-3 py-2 border-b border-slate-100 space-y-2">
            <div className="flex items-center gap-2">
              <div className="flex-1 flex items-center gap-1.5 bg-slate-100 rounded-lg px-2.5 py-1.5">
                <Search size={14} className="text-slate-400" />
                <input
                  value={searchQuery}
                  onChange={e => setSearchQuery(e.target.value)}
                  onKeyDown={e => e.key === 'Enter' && loadThreads()}
                  placeholder="Search emails..."
                  className="flex-1 bg-transparent text-sm outline-none text-slate-700 placeholder:text-slate-400"
                />
              </div>
              <button onClick={() => loadThreads()} className="text-slate-400 hover:text-slate-600"><RefreshCw size={16} /></button>
            </div>
            <div className="flex gap-1.5 flex-wrap">
              {['', 'open', 'assigned', 'snoozed', 'closed'].map(s => (
                <button key={s} onClick={() => { setFilterStatus(s); setPage(1); }}
                  className={`px-2 py-0.5 rounded text-[10px] font-semibold transition-colors ${
                    filterStatus === s ? 'bg-blue-100 text-blue-700' : 'bg-slate-100 text-slate-500 hover:bg-slate-200'
                  }`}>{s || 'All'}</button>
              ))}
            </div>
          </div>

          {/* Thread list */}
          <div className="flex-1 overflow-y-auto">
            {loading ? (
              <div className="flex items-center justify-center py-12"><Loader2 size={20} className="animate-spin text-slate-400" /></div>
            ) : threads.length === 0 ? (
              <div className="text-center py-12 text-slate-400 text-sm">
                <Mail size={28} className="mx-auto mb-2 opacity-40" />
                No emails found
              </div>
            ) : threads.map(t => (
              <button
                key={t.id}
                onClick={() => openThread(t)}
                className={`w-full text-left px-4 py-3 border-b border-slate-100 hover:bg-slate-50 transition-colors ${
                  activeThread?.id === t.id ? 'bg-blue-50 border-l-2 border-l-blue-500' : ''
                } ${t.is_unread ? 'bg-white' : 'bg-slate-50/50'}`}
              >
                <div className="flex items-start gap-3">
                  <div className="h-8 w-8 rounded-full flex items-center justify-center text-[10px] font-bold text-white flex-shrink-0 mt-0.5"
                    style={{ background: initColor(t.from_name || t.from_email) }}>
                    {getInitials(t.from_name || t.from_email)}
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center justify-between">
                      <span className={`text-sm truncate ${t.is_unread ? 'font-bold text-slate-900' : 'font-medium text-slate-700'}`}>
                        {t.from_name || t.from_email}
                      </span>
                      <span className="text-[10px] text-slate-400 flex-shrink-0 ml-2">{formatTime(t.last_message_at)}</span>
                    </div>
                    <div className={`text-xs truncate mt-0.5 ${t.is_unread ? 'font-semibold text-slate-800' : 'text-slate-600'}`}>
                      {t.subject}
                    </div>
                    <div className="text-[11px] text-slate-400 truncate mt-0.5">{t.preview}</div>
                    <div className="flex items-center gap-1.5 mt-1">
                      {t.tags?.map((tag: string) => (
                        <span key={tag} className="text-[9px] px-1.5 py-0.5 rounded bg-slate-100 text-slate-500 font-semibold">{tag}</span>
                      ))}
                      {t.assigned_to_name && (
                        <span className="text-[9px] px-1.5 py-0.5 rounded bg-purple-50 text-purple-600 font-semibold">→ {t.assigned_to_name.split(' ')[0]}</span>
                      )}
                      {t.customer_name && (
                        <span className="text-[9px] px-1.5 py-0.5 rounded bg-green-50 text-green-600 font-semibold">🔗 {t.customer_name.split(' ')[0]}</span>
                      )}
                      {t.priority === 'urgent' && <span className="text-[9px] px-1.5 py-0.5 rounded bg-red-100 text-red-600 font-bold">🔴 URGENT</span>}
                      {t.message_count > 1 && <span className="text-[9px] text-slate-400">{t.message_count} msgs</span>}
                    </div>
                  </div>
                </div>
              </button>
            ))}
          </div>
          {total > 30 && (
            <div className="px-4 py-2 border-t border-slate-100 flex justify-between items-center">
              <button disabled={page <= 1} onClick={() => setPage(p => p - 1)} className="text-xs text-slate-500 disabled:opacity-30">← Prev</button>
              <span className="text-[10px] text-slate-400">Page {page}</span>
              <button disabled={threads.length < 30} onClick={() => setPage(p => p + 1)} className="text-xs text-slate-500 disabled:opacity-30">Next →</button>
            </div>
          )}
        </div>

        {/* Right: Thread Detail / Message View */}
        <div className="flex-1 flex flex-col bg-white">
          {!activeThread ? (
            <div className="flex-1 flex flex-col items-center justify-center text-slate-400">
              <Mail size={48} className="opacity-20 mb-3" />
              <span className="text-lg font-medium">Select a conversation</span>
              <span className="text-sm mt-1">Choose an email thread from the left</span>
            </div>
          ) : (
            <>
              {/* Thread header */}
              <div className="px-6 py-3 border-b border-slate-100 bg-slate-50">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3 flex-1 min-w-0">
                    <button onClick={() => setActiveThread(null)} className="text-slate-400 hover:text-slate-600 lg:hidden"><ArrowLeft size={18} /></button>
                    <div className="min-w-0">
                      <h2 className="text-base font-bold text-slate-900 truncate">{activeThread.subject}</h2>
                      <div className="flex items-center gap-2 text-xs text-slate-500">
                        <span>{activeThread.from_name || activeThread.from_email}</span>
                        <span>·</span>
                        <span>{activeThread.message_count} messages</span>
                        {activeThread.customer_name && <><span>·</span><span className="text-green-600">🔗 {activeThread.customer_name}</span></>}
                      </div>
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    {/* Assign dropdown */}
                    <select
                      value={activeThread.assigned_to_id || ''}
                      onChange={e => handleAssign(activeThread.id, e.target.value ? parseInt(e.target.value) : null)}
                      className="text-xs border border-slate-200 rounded-lg px-2 py-1 bg-white"
                    >
                      <option value="">Unassigned</option>
                      {employees.map((e: any) => <option key={e.id} value={e.id}>{e.full_name}</option>)}
                    </select>
                    {/* Status actions */}
                    {activeThread.status !== 'closed' && (
                      <button onClick={() => handleStatus(activeThread.id, 'closed')}
                        className="flex items-center gap-1 text-xs text-green-600 hover:text-green-700 font-semibold px-2 py-1 rounded hover:bg-green-50">
                        <Archive size={13} /> Close
                      </button>
                    )}
                    {activeThread.status === 'closed' && (
                      <button onClick={() => handleStatus(activeThread.id, 'open')}
                        className="flex items-center gap-1 text-xs text-blue-600 hover:text-blue-700 font-semibold px-2 py-1 rounded hover:bg-blue-50">
                        <MailOpen size={13} /> Reopen
                      </button>
                    )}
                  </div>
                </div>
                {/* Tags */}
                <div className="flex items-center gap-1.5 mt-2">
                  {(activeThread.tags || []).map((tag: string) => (
                    <span key={tag} className="text-[10px] px-2 py-0.5 rounded-full bg-slate-200 text-slate-600 font-semibold cursor-pointer hover:bg-red-100 hover:text-red-600"
                      onClick={() => emailAPI.tag(activeThread.id, tag, 'remove').then(() => openThread(activeThread))}
                      title="Click to remove">
                      {tag} ×
                    </span>
                  ))}
                  <select className="text-[10px] border border-dashed border-slate-300 rounded px-1 py-0.5 text-slate-400 bg-transparent"
                    value="" onChange={e => { if (e.target.value) emailAPI.tag(activeThread.id, e.target.value).then(() => openThread(activeThread)); }}>
                    <option value="">+ Tag</option>
                    {TAGS.filter(t => !(activeThread.tags || []).includes(t)).map(t => <option key={t} value={t}>{t}</option>)}
                  </select>
                </div>
              </div>

              {/* Messages */}
              <div className="flex-1 overflow-y-auto px-6 py-4 space-y-4">
                {threadLoading ? (
                  <div className="flex items-center justify-center py-12"><Loader2 size={20} className="animate-spin text-slate-400" /></div>
                ) : messages.map((msg, i) => (
                  <div key={msg.id} className={`rounded-xl border p-4 ${
                    msg.direction === 'inbound'
                      ? 'bg-white border-slate-200'
                      : 'bg-blue-50 border-blue-200 ml-8'
                  }`}>
                    <div className="flex items-center justify-between mb-2">
                      <div className="flex items-center gap-2">
                        <div className="h-7 w-7 rounded-full flex items-center justify-center text-[9px] font-bold text-white"
                          style={{ background: initColor(msg.from_name || msg.from_email) }}>
                          {getInitials(msg.from_name || msg.from_email)}
                        </div>
                        <div>
                          <span className="text-sm font-semibold text-slate-800">{msg.from_name || msg.from_email}</span>
                          <span className="text-[10px] text-slate-400 ml-2">&lt;{msg.from_email}&gt;</span>
                        </div>
                      </div>
                      <span className="text-[10px] text-slate-400">{formatTime(msg.created_at)}</span>
                    </div>
                    {msg.to_emails?.length > 0 && (
                      <div className="text-[10px] text-slate-400 mb-2">
                        To: {msg.to_emails.join(', ')}
                        {msg.cc_emails?.length > 0 && <> · CC: {msg.cc_emails.join(', ')}</>}
                      </div>
                    )}
                    <div className="text-sm text-slate-700 whitespace-pre-wrap leading-relaxed">
                      {msg.body_text || '(No text content)'}
                    </div>
                    {msg.attachments?.length > 0 && (
                      <div className="mt-2 flex gap-2 flex-wrap">
                        {msg.attachments.map((att: any, ai: number) => (
                          <a key={ai} href={`${process.env.NEXT_PUBLIC_API_URL || 'https://better-choice-api.onrender.com'}${att.path}`}
                            target="_blank" rel="noopener noreferrer"
                            className="flex items-center gap-1 px-2 py-1 rounded bg-slate-100 hover:bg-slate-200 text-xs text-slate-600 transition-colors">
                            <Paperclip size={11} /> {att.filename} <span className="text-slate-400">({(att.size / 1024).toFixed(0)}KB)</span>
                          </a>
                        ))}
                      </div>
                    )}
                    {msg.nowcerts_logged && <span className="text-[9px] text-green-500 mt-1 inline-block">✓ Logged to NowCerts</span>}
                  </div>
                ))}
                <div ref={messagesEndRef} />
              </div>

              {/* Reply bar */}
              <div className="border-t border-slate-200 bg-slate-50">
                {!replyOpen ? (
                  <div className="px-6 py-3 flex items-center gap-3">
                    <button onClick={() => setReplyOpen(true)}
                      className="flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white text-sm font-semibold rounded-lg transition-colors">
                      <Send size={14} /> Reply
                    </button>
                    <button onClick={handleAiDraft} disabled={aiLoading}
                      className="flex items-center gap-2 px-4 py-2 bg-purple-50 hover:bg-purple-100 text-purple-700 text-sm font-semibold rounded-lg border border-purple-200 transition-colors disabled:opacity-50">
                      {aiLoading ? <Loader2 size={14} className="animate-spin" /> : <Sparkles size={14} />}
                      {aiLoading ? 'Drafting...' : 'AI Draft'}
                    </button>
                    {activeThread.status !== 'closed' && (
                      <button onClick={() => handleStatus(activeThread.id, 'closed')}
                        className="flex items-center gap-1.5 text-xs text-slate-500 hover:text-green-600 ml-auto">
                        <Archive size={13} /> Close without reply
                      </button>
                    )}
                  </div>
                ) : (
                  <div className="px-6 py-3 space-y-2">
                    {aiDraft && (
                      <div className="text-[10px] text-purple-600 font-semibold flex items-center gap-1 mb-1">
                        <Sparkles size={11} /> AI-generated draft — edit as needed
                      </div>
                    )}
                    <div className="flex gap-2 mb-2">
                      <button onClick={() => setReplySendAs('service')}
                        className={`px-3 py-1 rounded text-xs font-semibold border transition-colors ${
                          replySendAs === 'service' ? 'bg-blue-50 border-blue-300 text-blue-700' : 'bg-white border-slate-200 text-slate-500'
                        }`}>service@</button>
                      <button onClick={() => setReplySendAs('personal')}
                        className={`px-3 py-1 rounded text-xs font-semibold border transition-colors ${
                          replySendAs === 'personal' ? 'bg-blue-50 border-blue-300 text-blue-700' : 'bg-white border-slate-200 text-slate-500'
                        }`}>My Email</button>
                    </div>
                    <input value={replyCc} onChange={e => setReplyCc(e.target.value)} placeholder="CC (comma-separated)"
                      className="w-full border border-slate-200 rounded-lg px-3 py-1.5 text-xs" />
                    <textarea value={replyBody} onChange={e => setReplyBody(e.target.value)} rows={5} autoFocus
                      placeholder="Type your reply..."
                      className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm resize-none focus:ring-2 focus:ring-blue-500 outline-none" />
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-3">
                        <input ref={replyFileRef} type="file" multiple className="hidden"
                          onChange={e => { if (e.target.files) setReplyFiles(prev => [...prev, ...Array.from(e.target.files!)]); e.target.value = ''; }} />
                        <button onClick={() => replyFileRef.current?.click()} className="text-xs text-slate-500 hover:text-slate-700 flex items-center gap-1">
                          <Paperclip size={13} /> Attach
                        </button>
                        {replyFiles.map((f, i) => (
                          <span key={i} className="text-[10px] bg-slate-100 rounded px-1.5 py-0.5 text-slate-500">
                            {f.name} <button onClick={() => setReplyFiles(prev => prev.filter((_, j) => j !== i))} className="text-red-400 ml-1">×</button>
                          </span>
                        ))}
                        <label className="flex items-center gap-1 text-[10px] text-slate-400 cursor-pointer">
                          <input type="checkbox" checked={closeAfterReply} onChange={e => setCloseAfterReply(e.target.checked)} className="rounded" />
                          Close after send
                        </label>
                      </div>
                      <div className="flex items-center gap-2">
                        <button onClick={() => { setReplyOpen(false); setAiDraft(''); }} className="text-xs text-slate-500 hover:text-slate-700">Cancel</button>
                        <button disabled={!replyBody.trim() || replySending} onClick={handleReply}
                          className="flex items-center gap-1.5 px-4 py-1.5 bg-blue-600 hover:bg-blue-700 text-white text-xs font-semibold rounded-lg disabled:opacity-40 transition-colors">
                          {replySending ? <Loader2 size={13} className="animate-spin" /> : <Send size={13} />}
                          {replySending ? 'Sending...' : 'Send'}
                        </button>
                      </div>
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
