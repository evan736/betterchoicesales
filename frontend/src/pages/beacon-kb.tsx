import React, { useState, useEffect, useCallback, useRef } from 'react';
import { useRouter } from 'next/router';
import { useAuth } from '../contexts/AuthContext';
import Navbar from '../components/Navbar';
import {
  Zap, Upload, FileText, Image, MessageCircle, CheckCircle, XCircle,
  Clock, Search, Filter, ChevronDown, ChevronUp, Trash2, Edit3,
  BookOpen, AlertTriangle, X,
} from 'lucide-react';
import axios from 'axios';

const API = process.env.NEXT_PUBLIC_API_URL || 'https://better-choice-api.onrender.com';
function headers() { return { Authorization: `Bearer ${localStorage.getItem('token') || ''}` }; }

function timeAgo(iso: string) {
  if (!iso) return '';
  const diff = (Date.now() - new Date(iso).getTime()) / 1000;
  if (diff < 60) return 'just now';
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return new Date(iso).toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
}

const TYPE_ICONS: Record<string, any> = {
  pdf: { icon: FileText, color: 'text-red-400', bg: 'bg-red-500/15', label: 'PDF' },
  screenshot: { icon: Image, color: 'text-blue-400', bg: 'bg-blue-500/15', label: 'Screenshot' },
  correction: { icon: Edit3, color: 'text-amber-400', bg: 'bg-amber-500/15', label: 'Correction' },
  conversation: { icon: MessageCircle, color: 'text-purple-400', bg: 'bg-purple-500/15', label: 'Learned' },
};

const STATUS_STYLES: Record<string, any> = {
  approved: { color: 'text-emerald-300', bg: 'bg-emerald-500/15', border: 'border-emerald-500/20', icon: CheckCircle },
  pending: { color: 'text-amber-300', bg: 'bg-amber-500/15', border: 'border-amber-500/20', icon: Clock },
  rejected: { color: 'text-red-300', bg: 'bg-red-500/15', border: 'border-red-500/20', icon: XCircle },
};

export default function BeaconKnowledgeBase() {
  const { user, loading: authLoading } = useAuth();
  const router = useRouter();
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [entries, setEntries] = useState<any[]>([]);
  const [stats, setStats] = useState<any>({});
  const [loading, setLoading] = useState(true);
  const [expandedId, setExpandedId] = useState<number | null>(null);

  // Filters
  const [statusFilter, setStatusFilter] = useState<string>('');
  const [typeFilter, setTypeFilter] = useState<string>('');
  const [searchQuery, setSearchQuery] = useState('');

  // Upload modal
  const [showUpload, setShowUpload] = useState(false);
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [uploadTitle, setUploadTitle] = useState('');
  const [uploadCarrier, setUploadCarrier] = useState('');
  const [uploadTags, setUploadTags] = useState('');
  const [uploading, setUploading] = useState(false);
  const [uploadResult, setUploadResult] = useState<any>(null);

  // Correction modal
  const [showCorrection, setShowCorrection] = useState(false);
  const [correctionText, setCorrectionText] = useState('');
  const [correctionTitle, setCorrectionTitle] = useState('');
  const [correctionCarrier, setCorrectionCarrier] = useState('');
  const [screenshotCapturing, setScreenshotCapturing] = useState(false);

  // Clipboard paste handler for screenshots
  const [showPasteModal, setShowPasteModal] = useState(false);
  const [pastedImage, setPastedImage] = useState<File | null>(null);
  const [pastedPreview, setPastedPreview] = useState<string>('');
  const [pasteTitle, setPasteTitle] = useState('');
  const [pasteCarrier, setPasteCarrier] = useState('');
  const [pasteTags, setPasteTags] = useState('');

  const isManager = user && ['admin', 'manager', 'owner'].includes((user as any).role?.toLowerCase());

  useEffect(() => {
    if (!authLoading && !user) router.push('/');
    else if (user) { loadEntries(); loadStats(); }
  }, [user, authLoading]);

  const loadEntries = useCallback(async () => {
    try {
      const params: any = {};
      if (statusFilter) params.status = statusFilter;
      if (typeFilter) params.source_type = typeFilter;
      if (searchQuery) params.search = searchQuery;
      const res = await axios.get(`${API}/api/beacon-kb/entries`, { headers: headers(), params });
      setEntries(res.data.entries || []);
    } catch (e) { console.error(e); }
    finally { setLoading(false); }
  }, [statusFilter, typeFilter, searchQuery]);

  const loadStats = async () => {
    try {
      const res = await axios.get(`${API}/api/beacon-kb/stats`, { headers: headers() });
      setStats(res.data);
    } catch {}
  };

  useEffect(() => { loadEntries(); }, [statusFilter, typeFilter, searchQuery]);

  const handleUpload = async () => {
    if (!uploadFile) return;
    setUploading(true);
    setUploadResult(null);
    try {
      const fd = new FormData();
      fd.append('file', uploadFile);
      if (uploadTitle) fd.append('title', uploadTitle);
      if (uploadCarrier) fd.append('carrier', uploadCarrier);
      if (uploadTags) fd.append('tags', uploadTags);
      const res = await axios.post(`${API}/api/beacon-kb/upload`, fd, { headers: headers() });
      if (res.data.error) {
        setUploadResult({ error: res.data.error });
      } else {
        setUploadResult({ success: true, entry: res.data });
        setUploadFile(null);
        setUploadTitle('');
        setUploadCarrier('');
        setUploadTags('');
        loadEntries();
        loadStats();
      }
    } catch (e: any) {
      setUploadResult({ error: e.response?.data?.detail || 'Upload failed' });
    } finally { setUploading(false); }
  };

  const handleCorrection = async () => {
    if (!correctionText.trim()) return;
    try {
      await axios.post(`${API}/api/beacon-kb/correction`, {
        content: correctionText,
        title: correctionTitle || undefined,
        carrier: correctionCarrier || undefined,
      }, { headers: headers() });
      setShowCorrection(false);
      setCorrectionText('');
      setCorrectionTitle('');
      setCorrectionCarrier('');
      loadEntries();
      loadStats();
    } catch (e) { console.error(e); }
  };

  const handleApprove = async (id: number) => {
    try {
      await axios.post(`${API}/api/beacon-kb/entries/${id}/approve`, {}, { headers: headers() });
      loadEntries();
      loadStats();
    } catch (e) { console.error(e); }
  };

  const handleReject = async (id: number) => {
    try {
      await axios.post(`${API}/api/beacon-kb/entries/${id}/reject`, {}, { headers: headers() });
      loadEntries();
      loadStats();
    } catch (e) { console.error(e); }
  };

  const handleDelete = async (id: number) => {
    if (!confirm('Delete this knowledge entry?')) return;
    try {
      await axios.delete(`${API}/api/beacon-kb/entries/${id}`, { headers: headers() });
      loadEntries();
      loadStats();
    } catch (e) { console.error(e); }
  };

  // Screenshot capture — uses browser screen capture API
  const handleScreenCapture = async () => {
    setScreenshotCapturing(true);
    try {
      const stream = await navigator.mediaDevices.getDisplayMedia({
        video: { displaySurface: 'monitor' } as any,
      });
      
      // Grab a frame from the video stream
      const video = document.createElement('video');
      video.srcObject = stream;
      await video.play();
      
      // Wait a tick for the frame to render
      await new Promise(r => setTimeout(r, 200));
      
      const canvas = document.createElement('canvas');
      canvas.width = video.videoWidth;
      canvas.height = video.videoHeight;
      const ctx = canvas.getContext('2d');
      ctx?.drawImage(video, 0, 0);
      
      // Stop the stream
      stream.getTracks().forEach(t => t.stop());
      
      // Convert to blob
      const blob = await new Promise<Blob | null>(resolve => 
        canvas.toBlob(resolve, 'image/png')
      );
      
      if (blob) {
        const file = new File([blob], `screenshot-${Date.now()}.png`, { type: 'image/png' });
        const preview = canvas.toDataURL('image/png');
        setPastedImage(file);
        setPastedPreview(preview);
        setPasteTitle('');
        setPasteCarrier('');
        setPasteTags('');
        setShowPasteModal(true);
      }
    } catch (e: any) {
      // User cancelled the screen picker — that's fine
      if (e.name !== 'AbortError' && e.name !== 'NotAllowedError') {
        console.error('Screen capture failed:', e);
        alert('Screen capture failed. Try pasting a screenshot instead (Ctrl+V).');
      }
    } finally {
      setScreenshotCapturing(false);
    }
  };

  // Paste handler — listen for Ctrl+V with image data
  useEffect(() => {
    const handlePaste = (e: ClipboardEvent) => {
      const items = e.clipboardData?.items;
      if (!items) return;
      
      for (let i = 0; i < items.length; i++) {
        if (items[i].type.startsWith('image/')) {
          e.preventDefault();
          const blob = items[i].getAsFile();
          if (blob) {
            const file = new File([blob], `paste-${Date.now()}.png`, { type: blob.type });
            const reader = new FileReader();
            reader.onload = () => {
              setPastedImage(file);
              setPastedPreview(reader.result as string);
              setPasteTitle('');
              setPasteCarrier('');
              setPasteTags('');
              setShowPasteModal(true);
            };
            reader.readAsDataURL(blob);
          }
          break;
        }
      }
    };
    
    document.addEventListener('paste', handlePaste);
    return () => document.removeEventListener('paste', handlePaste);
  }, []);

  // Upload pasted/captured screenshot
  const handlePasteUpload = async () => {
    if (!pastedImage) return;
    setUploading(true);
    setUploadResult(null);
    try {
      const fd = new FormData();
      fd.append('file', pastedImage);
      if (pasteTitle) fd.append('title', pasteTitle);
      if (pasteCarrier) fd.append('carrier', pasteCarrier);
      if (pasteTags) fd.append('tags', pasteTags);
      const res = await axios.post(`${API}/api/beacon-kb/upload`, fd, { headers: headers() });
      if (res.data.error) {
        alert(res.data.error);
      } else {
        setShowPasteModal(false);
        setPastedImage(null);
        setPastedPreview('');
        loadEntries();
        loadStats();
      }
    } catch (e: any) {
      alert(e.response?.data?.detail || 'Upload failed');
    } finally { setUploading(false); }
  };

  if (!user) return null;

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-950 via-slate-900 to-slate-950 text-white">
      <Navbar />
      <div className="max-w-5xl mx-auto px-4 py-6">

        {/* Header */}
        <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 mb-6">
          <div>
            <h1 className="text-2xl font-bold flex items-center gap-3">
              <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-amber-500/20 to-orange-500/20 flex items-center justify-center">
                <BookOpen size={20} className="text-amber-400" />
              </div>
              BEACON Knowledge Base
            </h1>
            <p className="text-sm text-slate-400 mt-1">
              Teach BEACON what your team knows — PDFs, screenshots, corrections
            </p>
          </div>

          <div className="flex gap-2 flex-wrap">
            <button
              onClick={() => setShowCorrection(true)}
              className="flex items-center gap-1.5 px-3 py-2 bg-amber-500/10 hover:bg-amber-500/20 border border-amber-500/20 rounded-lg text-amber-300 text-xs font-semibold transition"
            >
              <Edit3 size={14} /> Add Correction
            </button>
            <button
              onClick={handleScreenCapture}
              disabled={screenshotCapturing}
              className="flex items-center gap-1.5 px-3 py-2 bg-violet-500/10 hover:bg-violet-500/20 border border-violet-500/20 rounded-lg text-violet-300 text-xs font-semibold transition disabled:opacity-50"
            >
              <Image size={14} /> {screenshotCapturing ? 'Capturing...' : '📸 Take Screenshot'}
            </button>
            <button
              onClick={() => setShowUpload(true)}
              className="flex items-center gap-1.5 px-3 py-2 bg-cyan-500/10 hover:bg-cyan-500/20 border border-cyan-500/20 rounded-lg text-cyan-300 text-xs font-semibold transition"
            >
              <Upload size={14} /> Upload File
            </button>
          </div>
          <div className="text-[10px] text-slate-500 mt-1">Tip: You can also paste screenshots with Ctrl+V anywhere on this page</div>
        </div>

        {/* Stats row */}
        <div className="grid grid-cols-2 sm:grid-cols-5 gap-3 mb-6">
          {[
            { label: 'Total', value: stats.total || 0, color: 'text-white' },
            { label: 'Approved', value: stats.approved || 0, color: 'text-emerald-400' },
            { label: 'Pending', value: stats.pending || 0, color: 'text-amber-400' },
            { label: 'PDFs', value: stats.by_type?.pdf || 0, color: 'text-red-400' },
            { label: 'Corrections', value: stats.by_type?.correction || 0, color: 'text-amber-400' },
          ].map((s, i) => (
            <div key={i} className="bg-white/[0.03] border border-white/[0.06] rounded-xl px-4 py-3 text-center">
              <div className={`text-xl font-bold ${s.color}`}>{s.value}</div>
              <div className="text-[10px] text-slate-500 uppercase">{s.label}</div>
            </div>
          ))}
        </div>

        {/* Filters */}
        <div className="flex flex-wrap items-center gap-2 mb-4">
          <div className="relative flex-1 min-w-[200px]">
            <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
            <input
              type="text"
              placeholder="Search knowledge..."
              value={searchQuery}
              onChange={e => setSearchQuery(e.target.value)}
              className="w-full pl-9 pr-3 py-2 bg-white/[0.04] border border-white/10 rounded-lg text-sm text-white placeholder-slate-500 focus:outline-none focus:border-cyan-500/40"
            />
          </div>
          <select
            value={statusFilter}
            onChange={e => setStatusFilter(e.target.value)}
            className="px-3 py-2 bg-white/[0.04] border border-white/10 rounded-lg text-sm text-slate-300 focus:outline-none"
          >
            <option value="">All Status</option>
            <option value="approved">Approved</option>
            <option value="pending">Pending</option>
            <option value="rejected">Rejected</option>
          </select>
          <select
            value={typeFilter}
            onChange={e => setTypeFilter(e.target.value)}
            className="px-3 py-2 bg-white/[0.04] border border-white/10 rounded-lg text-sm text-slate-300 focus:outline-none"
          >
            <option value="">All Types</option>
            <option value="pdf">PDFs</option>
            <option value="screenshot">Screenshots</option>
            <option value="correction">Corrections</option>
            <option value="conversation">Learned</option>
          </select>
        </div>

        {/* Entries list */}
        {loading ? (
          <div className="space-y-3">
            {[1,2,3].map(i => <div key={i} className="h-20 rounded-xl bg-white/5 animate-pulse" />)}
          </div>
        ) : entries.length === 0 ? (
          <div className="text-center py-16">
            <BookOpen size={40} className="mx-auto text-slate-600 mb-3" />
            <p className="text-slate-400">No knowledge entries yet</p>
            <p className="text-xs text-slate-500 mt-1">Upload a PDF or add a correction to get started</p>
          </div>
        ) : (
          <div className="space-y-2">
            {entries.map(entry => {
              const typeInfo = TYPE_ICONS[entry.source_type] || TYPE_ICONS.correction;
              const statusInfo = STATUS_STYLES[entry.status] || STATUS_STYLES.pending;
              const TypeIcon = typeInfo.icon;
              const StatusIcon = statusInfo.icon;
              const isExpanded = expandedId === entry.id;

              return (
                <div key={entry.id} className={`rounded-xl border transition-all ${
                  entry.status === 'pending' ? 'bg-amber-500/[0.02] border-amber-500/10' :
                  entry.status === 'rejected' ? 'bg-red-500/[0.02] border-red-500/10' :
                  'bg-white/[0.02] border-white/[0.06]'
                }`}>
                  <div className="flex items-center gap-3 p-4">
                    {/* Type icon */}
                    <div className={`w-9 h-9 rounded-lg ${typeInfo.bg} flex items-center justify-center flex-shrink-0`}>
                      <TypeIcon size={16} className={typeInfo.color} />
                    </div>

                    {/* Title + meta */}
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="text-sm font-semibold truncate">{entry.title}</span>
                        <span className={`text-[10px] px-2 py-0.5 rounded-full font-semibold ${statusInfo.bg} ${statusInfo.color} border ${statusInfo.border}`}>
                          {entry.status.toUpperCase()}
                        </span>
                      </div>
                      <div className="flex items-center gap-3 mt-0.5 text-[10px] text-slate-500">
                        <span>{typeInfo.label}</span>
                        {entry.carrier && <span>• {entry.carrier}</span>}
                        <span>• by {entry.submitted_by_name}</span>
                        <span>• {timeAgo(entry.created_at)}</span>
                      </div>
                    </div>

                    {/* Actions */}
                    <div className="flex items-center gap-1.5 flex-shrink-0">
                      {isManager && entry.status === 'pending' && (
                        <>
                          <button
                            onClick={() => handleApprove(entry.id)}
                            className="p-1.5 rounded-lg bg-emerald-500/10 hover:bg-emerald-500/20 text-emerald-400 transition"
                            title="Approve"
                          >
                            <CheckCircle size={14} />
                          </button>
                          <button
                            onClick={() => handleReject(entry.id)}
                            className="p-1.5 rounded-lg bg-red-500/10 hover:bg-red-500/20 text-red-400 transition"
                            title="Reject"
                          >
                            <XCircle size={14} />
                          </button>
                        </>
                      )}
                      {isManager && (
                        <button
                          onClick={() => handleDelete(entry.id)}
                          className="p-1.5 rounded-lg bg-white/5 hover:bg-red-500/10 text-slate-500 hover:text-red-400 transition"
                          title="Delete"
                        >
                          <Trash2 size={14} />
                        </button>
                      )}
                      <button
                        onClick={() => setExpandedId(isExpanded ? null : entry.id)}
                        className="p-1.5 rounded-lg bg-white/5 hover:bg-white/10 text-slate-400 transition"
                      >
                        {isExpanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                      </button>
                    </div>
                  </div>

                  {/* Expanded content */}
                  {isExpanded && (
                    <div className="px-4 pb-4 border-t border-white/5">
                      {entry.summary && (
                        <div className="mt-3 mb-2">
                          <p className="text-[10px] uppercase text-slate-500 mb-1">Summary</p>
                          <p className="text-xs text-slate-300">{entry.summary}</p>
                        </div>
                      )}
                      <div className="mt-2">
                        <p className="text-[10px] uppercase text-slate-500 mb-1">Full Content</p>
                        <pre className="text-xs text-slate-300 whitespace-pre-wrap bg-white/[0.02] rounded-lg p-3 max-h-64 overflow-y-auto" style={{ scrollbarWidth: 'thin' }}>
                          {entry.full_content}
                        </pre>
                      </div>
                      {entry.tags && (
                        <div className="mt-2 flex items-center gap-1.5">
                          <span className="text-[10px] text-slate-500">Tags:</span>
                          {entry.tags.split(',').map((t: string, i: number) => (
                            <span key={i} className="text-[10px] px-2 py-0.5 bg-cyan-500/10 text-cyan-300 rounded-full">
                              {t.trim()}
                            </span>
                          ))}
                        </div>
                      )}
                      {entry.reviewed_by_name && (
                        <p className="text-[10px] text-slate-500 mt-2">
                          Reviewed by {entry.reviewed_by_name} {entry.reviewed_at ? timeAgo(entry.reviewed_at) : ''}
                          {entry.review_note ? ` — "${entry.review_note}"` : ''}
                        </p>
                      )}
                      {entry.original_filename && (
                        <p className="text-[10px] text-slate-500 mt-1">File: {entry.original_filename}</p>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* Upload Modal */}
      {showUpload && (
        <div className="fixed inset-0 z-50 bg-black/60 flex items-center justify-center p-4" onClick={() => setShowUpload(false)}>
          <div className="bg-slate-900 border border-white/10 rounded-2xl max-w-lg w-full p-6" onClick={e => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-lg font-bold flex items-center gap-2">
                <Upload size={18} className="text-cyan-400" />
                Upload Knowledge
              </h2>
              <button onClick={() => setShowUpload(false)} className="text-slate-400 hover:text-white">
                <X size={18} />
              </button>
            </div>

            <p className="text-xs text-slate-400 mb-4">
              Upload a carrier PDF or screenshot. BEACON will extract the text and learn from it.
              {!isManager && ' A manager will need to approve it before BEACON uses it.'}
            </p>

            {/* File drop zone */}
            <div
              onClick={() => fileInputRef.current?.click()}
              className="border-2 border-dashed border-white/10 hover:border-cyan-500/30 rounded-xl p-6 text-center cursor-pointer transition mb-4"
            >
              {uploadFile ? (
                <div className="flex items-center justify-center gap-2">
                  {uploadFile.type.includes('pdf') ? <FileText size={20} className="text-red-400" /> : <Image size={20} className="text-blue-400" />}
                  <span className="text-sm text-white">{uploadFile.name}</span>
                  <span className="text-[10px] text-slate-500">({(uploadFile.size / 1024).toFixed(0)} KB)</span>
                </div>
              ) : (
                <>
                  <Upload size={24} className="mx-auto text-slate-500 mb-2" />
                  <p className="text-sm text-slate-400">Click to select a PDF or image</p>
                  <p className="text-[10px] text-slate-600 mt-1">Supports: PDF, PNG, JPG, WEBP</p>
                </>
              )}
              <input
                ref={fileInputRef}
                type="file"
                accept=".pdf,.png,.jpg,.jpeg,.gif,.webp"
                className="hidden"
                onChange={e => setUploadFile(e.target.files?.[0] || null)}
              />
            </div>

            <input
              type="text"
              placeholder="Title (optional — auto-generated from filename)"
              value={uploadTitle}
              onChange={e => setUploadTitle(e.target.value)}
              className="w-full px-3 py-2 mb-3 bg-white/[0.04] border border-white/10 rounded-lg text-sm text-white placeholder-slate-500 focus:outline-none focus:border-cyan-500/40"
            />
            <div className="flex gap-3 mb-4">
              <input
                type="text"
                placeholder="Carrier (e.g. NatGen)"
                value={uploadCarrier}
                onChange={e => setUploadCarrier(e.target.value)}
                className="flex-1 px-3 py-2 bg-white/[0.04] border border-white/10 rounded-lg text-sm text-white placeholder-slate-500 focus:outline-none focus:border-cyan-500/40"
              />
              <input
                type="text"
                placeholder="Tags (comma sep)"
                value={uploadTags}
                onChange={e => setUploadTags(e.target.value)}
                className="flex-1 px-3 py-2 bg-white/[0.04] border border-white/10 rounded-lg text-sm text-white placeholder-slate-500 focus:outline-none focus:border-cyan-500/40"
              />
            </div>

            {uploadResult?.error && (
              <div className="bg-red-500/10 border border-red-500/20 rounded-lg p-3 mb-3 text-xs text-red-300 flex items-center gap-2">
                <AlertTriangle size={14} /> {uploadResult.error}
              </div>
            )}
            {uploadResult?.success && (
              <div className="bg-emerald-500/10 border border-emerald-500/20 rounded-lg p-3 mb-3 text-xs text-emerald-300 flex items-center gap-2">
                <CheckCircle size={14} /> Uploaded! {isManager ? 'Auto-approved.' : 'Pending manager approval.'}
              </div>
            )}

            <button
              onClick={handleUpload}
              disabled={!uploadFile || uploading}
              className="w-full py-2.5 bg-cyan-500 hover:bg-cyan-400 disabled:bg-slate-700 disabled:text-slate-500 rounded-lg text-sm font-semibold text-white transition"
            >
              {uploading ? 'Processing...' : 'Upload & Extract'}
            </button>
          </div>
        </div>
      )}

      {/* Correction Modal */}
      {showCorrection && (
        <div className="fixed inset-0 z-50 bg-black/60 flex items-center justify-center p-4" onClick={() => setShowCorrection(false)}>
          <div className="bg-slate-900 border border-white/10 rounded-2xl max-w-lg w-full p-6" onClick={e => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-lg font-bold flex items-center gap-2">
                <Edit3 size={18} className="text-amber-400" />
                Add Correction
              </h2>
              <button onClick={() => setShowCorrection(false)} className="text-slate-400 hover:text-white">
                <X size={18} />
              </button>
            </div>

            <p className="text-xs text-slate-400 mb-4">
              BEACON got something wrong? Add a correction so it knows better next time.
              {!isManager && ' A manager will need to approve it first.'}
            </p>

            <input
              type="text"
              placeholder="Short title (e.g. 'NatGen trampoline rule in OH')"
              value={correctionTitle}
              onChange={e => setCorrectionTitle(e.target.value)}
              className="w-full px-3 py-2 mb-3 bg-white/[0.04] border border-white/10 rounded-lg text-sm text-white placeholder-slate-500 focus:outline-none focus:border-cyan-500/40"
            />
            <textarea
              placeholder="Describe the correction... (e.g. 'NatGen does NOT write trampolines in Ohio without an enclosure. BEACON said they were okay but that's only with safety netting.')"
              value={correctionText}
              onChange={e => setCorrectionText(e.target.value)}
              rows={4}
              className="w-full px-3 py-2 mb-3 bg-white/[0.04] border border-white/10 rounded-lg text-sm text-white placeholder-slate-500 focus:outline-none focus:border-cyan-500/40 resize-none"
            />
            <input
              type="text"
              placeholder="Carrier (optional)"
              value={correctionCarrier}
              onChange={e => setCorrectionCarrier(e.target.value)}
              className="w-full px-3 py-2 mb-4 bg-white/[0.04] border border-white/10 rounded-lg text-sm text-white placeholder-slate-500 focus:outline-none focus:border-cyan-500/40"
            />

            <button
              onClick={handleCorrection}
              disabled={!correctionText.trim()}
              className="w-full py-2.5 bg-amber-500 hover:bg-amber-400 disabled:bg-slate-700 disabled:text-slate-500 rounded-lg text-sm font-semibold text-white transition"
            >
              Submit Correction
            </button>
          </div>
        </div>
      )}

      {/* Screenshot / Paste Preview Modal */}
      {showPasteModal && pastedPreview && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4">
          <div className="bg-slate-900 border border-white/10 rounded-2xl w-full max-w-2xl max-h-[90vh] overflow-y-auto shadow-2xl">
            <div className="flex items-center justify-between px-6 py-4 border-b border-white/10">
              <h3 className="text-lg font-bold text-white flex items-center gap-2">
                <Image size={20} className="text-violet-400" />
                Add Screenshot to Knowledge Base
              </h3>
              <button onClick={() => { setShowPasteModal(false); setPastedImage(null); setPastedPreview(''); }} className="text-slate-400 hover:text-white">
                <X size={20} />
              </button>
            </div>
            <div className="p-6 space-y-4">
              {/* Preview */}
              <div className="rounded-lg border border-white/10 overflow-hidden bg-black/30">
                <img src={pastedPreview} alt="Screenshot preview" className="w-full max-h-64 object-contain" />
              </div>
              
              {/* Title */}
              <div>
                <label className="text-xs text-slate-400 font-medium mb-1 block">Title</label>
                <input
                  value={pasteTitle}
                  onChange={e => setPasteTitle(e.target.value)}
                  placeholder="e.g. Lender Contacts, NatGen Auto Guidelines..."
                  className="w-full px-3 py-2 bg-white/5 border border-white/10 rounded-lg text-sm text-white placeholder-slate-500 focus:border-violet-500/50 focus:outline-none"
                />
              </div>

              {/* Carrier */}
              <div>
                <label className="text-xs text-slate-400 font-medium mb-1 block">Carrier (optional)</label>
                <input
                  value={pasteCarrier}
                  onChange={e => setPasteCarrier(e.target.value)}
                  placeholder="e.g. National General, Progressive..."
                  className="w-full px-3 py-2 bg-white/5 border border-white/10 rounded-lg text-sm text-white placeholder-slate-500 focus:border-violet-500/50 focus:outline-none"
                />
              </div>

              {/* Tags */}
              <div>
                <label className="text-xs text-slate-400 font-medium mb-1 block">Tags (optional, comma-separated)</label>
                <input
                  value={pasteTags}
                  onChange={e => setPasteTags(e.target.value)}
                  placeholder="e.g. guidelines, contacts, rates..."
                  className="w-full px-3 py-2 bg-white/5 border border-white/10 rounded-lg text-sm text-white placeholder-slate-500 focus:border-violet-500/50 focus:outline-none"
                />
              </div>

              <button
                onClick={handlePasteUpload}
                disabled={uploading}
                className="w-full py-2.5 bg-violet-500 hover:bg-violet-400 disabled:bg-slate-700 disabled:text-slate-500 rounded-lg text-sm font-semibold text-white transition flex items-center justify-center gap-2"
              >
                {uploading ? (
                  <><span className="animate-spin">⏳</span> Processing with AI...</>
                ) : (
                  <><Upload size={14} /> Add to Knowledge Base</>
                )}
              </button>
              <p className="text-[10px] text-slate-500 text-center">AI will extract all text and information from the screenshot</p>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
