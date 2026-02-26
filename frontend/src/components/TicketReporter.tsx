import React, { useState, useRef, useCallback } from 'react';
import { Bug, Camera, X, Send, Loader2, CheckCircle2, AlertTriangle } from 'lucide-react';
import { useAuth } from '../contexts/AuthContext';

const API = process.env.NEXT_PUBLIC_API_URL || '';

interface TicketReporterProps {}

const TicketReporter: React.FC<TicketReporterProps> = () => {
  const { user, token } = useAuth();
  const [open, setOpen] = useState(false);
  const [description, setDescription] = useState('');
  const [priority, setPriority] = useState<'low' | 'normal' | 'high' | 'critical'>('normal');
  const [screenshot, setScreenshot] = useState<string | null>(null);
  const [capturing, setCapturing] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const [ticketId, setTicketId] = useState<number | null>(null);
  const [error, setError] = useState('');
  const fileRef = useRef<HTMLInputElement>(null);

  const captureScreenshot = useCallback(async () => {
    setCapturing(true);
    try {
      // Dynamically import html2canvas
      const html2canvas = (await import('html2canvas')).default;

      // Hide the ticket modal temporarily for clean screenshot
      const modal = document.getElementById('ticket-modal');
      if (modal) modal.style.display = 'none';

      const canvas = await html2canvas(document.body, {
        useCORS: true,
        allowTaint: true,
        scale: 0.75, // Reduce size for storage
        logging: false,
        ignoreElements: (el) => el.id === 'ticket-reporter-fab',
      });

      if (modal) modal.style.display = '';

      const dataUrl = canvas.toDataURL('image/png', 0.7);
      setScreenshot(dataUrl);
    } catch (err) {
      console.error('Screenshot failed:', err);
      // Fallback: let user manually upload
      setError('Auto-screenshot failed — you can paste or upload an image instead');
    }
    setCapturing(false);
  }, []);

  const handleFileUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => setScreenshot(reader.result as string);
    reader.readAsDataURL(file);
  };

  const handlePaste = useCallback((e: React.ClipboardEvent) => {
    const items = e.clipboardData?.items;
    if (!items) return;
    for (let i = 0; i < items.length; i++) {
      if (items[i].type.startsWith('image/')) {
        const file = items[i].getAsFile();
        if (file) {
          const reader = new FileReader();
          reader.onload = () => setScreenshot(reader.result as string);
          reader.readAsDataURL(file);
        }
        break;
      }
    }
  }, []);

  const handleOpen = async () => {
    setOpen(true);
    setSubmitted(false);
    setError('');
    setDescription('');
    setPriority('normal');
    setScreenshot(null);
    setTicketId(null);
    // Auto-capture screenshot when opening
    setTimeout(() => captureScreenshot(), 100);
  };

  const handleSubmit = async () => {
    if (!description.trim()) {
      setError('Please describe the issue');
      return;
    }
    setSubmitting(true);
    setError('');
    try {
      const resp = await fetch(`${API}/api/tickets`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`,
        },
        body: JSON.stringify({
          description: description.trim(),
          page_url: window.location.href,
          user_agent: navigator.userAgent,
          screenshot_data: screenshot || null,
          priority,
        }),
      });
      if (!resp.ok) {
        const data = await resp.json().catch(() => ({}));
        throw new Error(data.detail || 'Failed to create ticket');
      }
      const data = await resp.json();
      setTicketId(data.id);
      setSubmitted(true);
    } catch (err: any) {
      setError(err.message || 'Failed to submit ticket');
    }
    setSubmitting(false);
  };

  const handleClose = () => {
    setOpen(false);
    setDescription('');
    setScreenshot(null);
    setSubmitted(false);
    setError('');
  };

  if (!user) return null;

  const priorityOptions = [
    { value: 'low', label: 'Low', color: 'text-slate-400' },
    { value: 'normal', label: 'Normal', color: 'text-blue-400' },
    { value: 'high', label: 'High', color: 'text-amber-400' },
    { value: 'critical', label: 'Critical', color: 'text-red-400' },
  ];

  return (
    <>
      {/* Floating Action Button */}
      <button
        id="ticket-reporter-fab"
        onClick={handleOpen}
        className="fixed bottom-5 right-5 z-50 w-12 h-12 rounded-full bg-red-500 hover:bg-red-600 text-white shadow-lg shadow-red-500/30 flex items-center justify-center transition-all hover:scale-110 active:scale-95"
        title="Report an Issue"
      >
        <Bug size={20} />
      </button>

      {/* Modal Overlay */}
      {open && (
        <div className="fixed inset-0 z-[9999] flex items-center justify-center p-4 bg-black/50 backdrop-blur-sm">
          <div
            id="ticket-modal"
            className="w-full max-w-lg bg-slate-900 rounded-2xl border border-slate-700/50 shadow-2xl overflow-hidden"
            onPaste={handlePaste}
          >
            {/* Header */}
            <div className="flex items-center justify-between px-5 py-4 border-b border-slate-700/50 bg-slate-800/50">
              <div className="flex items-center gap-3">
                <div className="w-8 h-8 rounded-lg bg-red-500/20 flex items-center justify-center">
                  <Bug size={16} className="text-red-400" />
                </div>
                <div>
                  <h2 className="text-sm font-bold text-white">Report an Issue</h2>
                  <p className="text-xs text-slate-400">Screenshot captured automatically</p>
                </div>
              </div>
              <button onClick={handleClose} className="p-1.5 rounded-lg hover:bg-slate-700 transition-colors">
                <X size={16} className="text-slate-400" />
              </button>
            </div>

            {submitted ? (
              /* Success State */
              <div className="p-8 text-center">
                <div className="w-14 h-14 rounded-full bg-emerald-500/20 flex items-center justify-center mx-auto mb-4">
                  <CheckCircle2 size={28} className="text-emerald-400" />
                </div>
                <h3 className="text-lg font-bold text-white mb-2">Ticket #{ticketId} Created</h3>
                <p className="text-sm text-slate-400 mb-6">Thanks for reporting! We'll look into it.</p>
                <button
                  onClick={handleClose}
                  className="px-5 py-2 rounded-lg bg-slate-700 hover:bg-slate-600 text-white text-sm font-medium transition-colors"
                >
                  Close
                </button>
              </div>
            ) : (
              /* Form */
              <div className="p-5 space-y-4">
                {/* Screenshot Preview */}
                <div>
                  <label className="text-xs font-semibold text-slate-400 mb-2 block">Screenshot</label>
                  {capturing ? (
                    <div className="flex items-center justify-center h-32 rounded-lg bg-slate-800 border border-slate-700">
                      <Loader2 size={20} className="animate-spin text-slate-500" />
                      <span className="ml-2 text-sm text-slate-500">Capturing...</span>
                    </div>
                  ) : screenshot ? (
                    <div className="relative group">
                      <img
                        src={screenshot}
                        alt="Screenshot"
                        className="w-full h-40 object-cover rounded-lg border border-slate-700"
                      />
                      <div className="absolute inset-0 rounded-lg bg-black/0 group-hover:bg-black/30 transition-colors flex items-center justify-center opacity-0 group-hover:opacity-100">
                        <button
                          onClick={captureScreenshot}
                          className="px-3 py-1.5 rounded-lg bg-white/20 backdrop-blur text-white text-xs font-medium"
                        >
                          <Camera size={12} className="inline mr-1" /> Retake
                        </button>
                      </div>
                    </div>
                  ) : (
                    <div className="flex flex-col items-center justify-center h-32 rounded-lg bg-slate-800 border border-dashed border-slate-600">
                      <button
                        onClick={captureScreenshot}
                        className="flex items-center gap-2 px-4 py-2 rounded-lg bg-cyan-500/20 text-cyan-300 text-sm font-medium hover:bg-cyan-500/30 transition-colors"
                      >
                        <Camera size={14} /> Capture Screenshot
                      </button>
                      <p className="text-xs text-slate-500 mt-2">or paste an image (Ctrl+V) or
                        <button onClick={() => fileRef.current?.click()} className="text-cyan-400 hover:underline ml-1">upload</button>
                      </p>
                      <input ref={fileRef} type="file" accept="image/*" onChange={handleFileUpload} className="hidden" />
                    </div>
                  )}
                </div>

                {/* Description */}
                <div>
                  <label className="text-xs font-semibold text-slate-400 mb-1.5 block">What's the issue? *</label>
                  <textarea
                    value={description}
                    onChange={e => setDescription(e.target.value)}
                    placeholder="Describe what you were trying to do and what went wrong..."
                    rows={4}
                    className="w-full px-3 py-2.5 rounded-lg bg-slate-800 border border-slate-700 text-sm text-white placeholder-slate-500 focus:border-cyan-500 focus:ring-1 focus:ring-cyan-500 outline-none resize-none"
                    autoFocus
                  />
                </div>

                {/* Priority */}
                <div>
                  <label className="text-xs font-semibold text-slate-400 mb-1.5 block">Priority</label>
                  <div className="flex gap-2">
                    {priorityOptions.map(p => (
                      <button
                        key={p.value}
                        onClick={() => setPriority(p.value as any)}
                        className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${
                          priority === p.value
                            ? 'bg-slate-700 ring-1 ring-cyan-500 text-white'
                            : 'bg-slate-800 text-slate-400 hover:bg-slate-700'
                        }`}
                      >
                        {p.label}
                      </button>
                    ))}
                  </div>
                </div>

                {/* Page URL (read-only) */}
                <div className="text-xs text-slate-500 truncate">
                  Page: {typeof window !== 'undefined' ? window.location.pathname : ''}
                </div>

                {/* Error */}
                {error && (
                  <div className="flex items-center gap-2 text-sm text-red-400">
                    <AlertTriangle size={14} /> {error}
                  </div>
                )}

                {/* Actions */}
                <div className="flex items-center justify-end gap-3 pt-2">
                  <button
                    onClick={handleClose}
                    className="px-4 py-2 rounded-lg text-sm text-slate-400 hover:text-white hover:bg-slate-700 transition-colors"
                  >
                    Cancel
                  </button>
                  <button
                    onClick={handleSubmit}
                    disabled={submitting || !description.trim()}
                    className="flex items-center gap-2 px-5 py-2 rounded-lg bg-red-500 hover:bg-red-600 disabled:bg-slate-700 disabled:text-slate-500 text-white text-sm font-semibold transition-colors"
                  >
                    {submitting ? <Loader2 size={14} className="animate-spin" /> : <Send size={14} />}
                    Submit Ticket
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </>
  );
};

export default TicketReporter;
