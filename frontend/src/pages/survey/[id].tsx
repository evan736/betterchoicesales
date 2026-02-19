import React, { useEffect, useState } from 'react';
import { useRouter } from 'next/router';
import api from '../../lib/api';

// Hard-code the Google Review URL here so the frontend can redirect
// even if the backend env var is not set. Update this with your actual link.
const GOOGLE_REVIEW_URL = 'https://g.page/r/CcqT2a9FrSoXEBM/review';

const SurveyPage = () => {
  const router = useRouter();
  const { id, rating: urlRating } = router.query;
  const [info, setInfo] = useState<any>(null);
  const [selectedRating, setSelectedRating] = useState<number | null>(null);
  const [feedback, setFeedback] = useState('');
  const [phase, setPhase] = useState<
    'loading' | 'error' | 'rate' | 'redirecting' | 'feedback_form' | 'feedback_sent' | 'thankyou'
  >('loading');

  // Feedback form fields
  const [feedbackName, setFeedbackName] = useState('');
  const [feedbackEmail, setFeedbackEmail] = useState('');
  const [feedbackMessage, setFeedbackMessage] = useState('');
  const [sendingFeedback, setSendingFeedback] = useState(false);

  useEffect(() => {
    if (!router.isReady || !id) return;
    loadSurveyInfo();
  }, [router.isReady, id]);

  useEffect(() => {
    if (urlRating && info && phase === 'rate') {
      const r = parseInt(urlRating as string);
      if (r >= 1 && r <= 5) {
        setSelectedRating(r);
        handleSubmit(r);
      }
    }
  }, [urlRating, info, phase]);

  const loadSurveyInfo = async () => {
    try {
      const res = await api.get(`/api/survey/info/${id}`);
      setInfo(res.data);
      if (res.data.already_submitted) {
        // If they came from an email star link, still route them properly
        const rFromUrl = urlRating ? parseInt(urlRating as string) : 0;
        if (rFromUrl >= 4) {
          setPhase('redirecting');
          setTimeout(() => {
            window.location.href = GOOGLE_REVIEW_URL;
          }, 2500);
        } else if (rFromUrl >= 1) {
          setFeedbackName(res.data.client_name || '');
          setPhase('feedback_form');
        } else {
          setPhase('thankyou');
        }
      } else {
        setPhase('rate');
      }
    } catch (err) {
      setPhase('error');
    }
  };

  const handleSubmit = async (rating?: number) => {
    const r = rating || selectedRating;
    if (!r || !id) return;

    try {
      await api.post('/api/survey/submit', null, {
        params: { sale_id: id, rating: r, feedback: feedback || undefined },
      });

      // Route based on rating — decided client-side
      if (r >= 4) {
        // 4-5 stars: redirect to Google Review
        setPhase('redirecting');
        setTimeout(() => {
          window.location.href = GOOGLE_REVIEW_URL;
        }, 2500);
      } else {
        // 1-3 stars: show feedback form
        setFeedbackName(info?.client_name || '');
        setPhase('feedback_form');
      }
    } catch (err: any) {
      // If already submitted, still route them
      if (r >= 4) {
        setPhase('redirecting');
        setTimeout(() => {
          window.location.href = GOOGLE_REVIEW_URL;
        }, 2500);
      } else {
        setFeedbackName(info?.client_name || '');
        setPhase('feedback_form');
      }
    }
  };

  const handleSendFeedback = async () => {
    if (!feedbackMessage.trim()) return;
    setSendingFeedback(true);

    // Try to send via backend API first (so it's captured in the database)
    try {
      await api.post('/api/survey/feedback', {
        sale_id: parseInt(id as string),
        name: feedbackName,
        email: feedbackEmail,
        message: feedbackMessage,
        rating: selectedRating,
      });
    } catch (err) {
      // If backend endpoint doesn't exist yet, fall back to mailto
      const subject = encodeURIComponent(
        `Customer Feedback - ${feedbackName || info?.client_name || 'Customer'} (${selectedRating} star)`
      );
      const body = encodeURIComponent(
        `Name: ${feedbackName || info?.client_name || ''}\n` +
        `Email: ${feedbackEmail}\n` +
        `Policy: ${info?.policy_number || ''}\n` +
        `Carrier: ${info?.carrier || ''}\n` +
        `Rating: ${selectedRating} out of 5 stars\n\n` +
        `Feedback:\n${feedbackMessage}\n`
      );
      window.open(`mailto:evan@betterchoiceins.com?subject=${subject}&body=${body}`, '_self');
    }

    setPhase('feedback_sent');
  };

  // ─── LOADING ───────────────────────────────────────────────
  if (phase === 'loading') {
    return (
      <div className="min-h-screen bg-gradient-to-br from-slate-50 to-purple-50 flex items-center justify-center">
        <div className="text-slate-500 animate-pulse">Loading...</div>
      </div>
    );
  }

  // ─── ERROR ─────────────────────────────────────────────────
  if (phase === 'error') {
    return (
      <div className="min-h-screen bg-gradient-to-br from-slate-50 to-purple-50 flex items-center justify-center">
        <div className="bg-white rounded-2xl shadow-lg p-8 text-center max-w-md">
          <div className="text-4xl mb-4">😕</div>
          <h1 className="text-xl font-bold text-slate-900 mb-2">Survey Not Found</h1>
          <p className="text-slate-500">This survey link may have expired or is invalid.</p>
        </div>
      </div>
    );
  }

  // ─── REDIRECTING TO GOOGLE (4-5 stars) ─────────────────────
  if (phase === 'redirecting') {
    return (
      <div className="min-h-screen bg-gradient-to-br from-green-50 to-emerald-50 flex items-center justify-center p-4">
        <div className="bg-white rounded-2xl shadow-lg p-8 text-center max-w-md w-full">
          <div className="text-5xl mb-4">🌟</div>
          <h1 className="text-2xl font-bold text-slate-900 mb-2">Thank you so much!</h1>
          <p className="text-slate-600 mb-4">
            We&apos;re thrilled you had a great experience with {info?.producer_name}!
          </p>
          <p className="text-green-700 font-semibold mb-4">
            Redirecting you to leave a Google review...
          </p>
          <div className="animate-spin w-6 h-6 border-2 border-green-600 border-t-transparent rounded-full mx-auto mb-6"></div>
          <a
            href={GOOGLE_REVIEW_URL}
            className="text-sm text-green-600 hover:underline"
          >
            Click here if not redirected automatically
          </a>
        </div>
      </div>
    );
  }

  // ─── FEEDBACK FORM (1-3 stars) ─────────────────────────────
  if (phase === 'feedback_form') {
    return (
      <div className="min-h-screen bg-gradient-to-br from-slate-50 to-blue-50 flex items-center justify-center p-4">
        <div className="bg-white rounded-2xl shadow-lg p-8 max-w-lg w-full">
          <div className="text-center mb-6">
            <img src="/logo-bci.png" alt="Better Choice Insurance Group" className="h-14 w-auto mx-auto mb-4" />
            <div className="text-4xl mb-3">💬</div>
            <h1 className="text-2xl font-bold text-slate-900 mb-2">
              We want to make it right
            </h1>
            <p className="text-slate-600">
              We&apos;re sorry your experience wasn&apos;t 100% satisfactory.
              Please share more details so we can address your concerns directly.
            </p>
          </div>

          <div className="space-y-4">
            <div>
              <label className="block text-sm font-semibold text-slate-700 mb-1">Your Name</label>
              <input
                type="text"
                value={feedbackName}
                onChange={(e) => setFeedbackName(e.target.value)}
                className="w-full border border-slate-300 rounded-xl px-4 py-3 text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none"
                placeholder="Your full name"
              />
            </div>

            <div>
              <label className="block text-sm font-semibold text-slate-700 mb-1">Your Email</label>
              <input
                type="email"
                value={feedbackEmail}
                onChange={(e) => setFeedbackEmail(e.target.value)}
                className="w-full border border-slate-300 rounded-xl px-4 py-3 text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none"
                placeholder="So we can follow up with you"
              />
            </div>

            <div>
              <label className="block text-sm font-semibold text-slate-700 mb-1">
                What could we have done better?
              </label>
              <textarea
                value={feedbackMessage}
                onChange={(e) => setFeedbackMessage(e.target.value)}
                className="w-full border border-slate-300 rounded-xl px-4 py-3 text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none"
                rows={5}
                placeholder="Please tell us about your experience — we take every response seriously and will follow up personally."
              />
            </div>

            <button
              onClick={handleSendFeedback}
              disabled={!feedbackMessage.trim() || sendingFeedback}
              className={`w-full font-semibold py-3.5 rounded-xl text-lg transition-all shadow-lg ${
                feedbackMessage.trim() && !sendingFeedback
                  ? 'bg-gradient-to-r from-blue-600 to-indigo-600 text-white hover:from-blue-700 hover:to-indigo-700'
                  : 'bg-slate-200 text-slate-400 cursor-not-allowed'
              }`}
            >
              {sendingFeedback ? 'Sending...' : '✉️ Send Feedback'}
            </button>
          </div>

          <div className="mt-6 pt-4 border-t border-slate-100 text-center">
            <p className="text-xs text-slate-400">
              You can also reach us directly at{' '}
              <a href="mailto:evan@betterchoiceins.com" className="text-blue-600 hover:underline">
                evan@betterchoiceins.com
              </a>
            </p>
            <p className="text-xs text-slate-400 mt-1">
              Policy: {info?.policy_number} • {info?.carrier?.replace('_', ' ')}
            </p>
          </div>
        </div>
      </div>
    );
  }

  // ─── FEEDBACK SENT CONFIRMATION ────────────────────────────
  if (phase === 'feedback_sent') {
    return (
      <div className="min-h-screen bg-gradient-to-br from-slate-50 to-blue-50 flex items-center justify-center p-4">
        <div className="bg-white rounded-2xl shadow-lg p-8 text-center max-w-md w-full">
          <div className="text-5xl mb-4">✅</div>
          <h1 className="text-2xl font-bold text-slate-900 mb-2">Thank You for Your Feedback</h1>
          <p className="text-slate-600 mb-4">
            We take your concerns seriously and will reach out to you personally to make things right.
          </p>
          <p className="text-sm text-slate-500">
            — The Better Choice Insurance Team
          </p>
        </div>
      </div>
    );
  }

  // ─── ALREADY SUBMITTED ─────────────────────────────────────
  if (phase === 'thankyou') {
    return (
      <div className="min-h-screen bg-gradient-to-br from-slate-50 to-purple-50 flex items-center justify-center p-4">
        <div className="bg-white rounded-2xl shadow-lg p-8 text-center max-w-md w-full">
          <div className="text-5xl mb-4">🙏</div>
          <h1 className="text-2xl font-bold text-slate-900 mb-2">Thank You!</h1>
          <p className="text-slate-600">
            Your feedback helps us improve. We appreciate you choosing Better Choice Insurance Group!
          </p>
        </div>
      </div>
    );
  }

  // ─── RATING FORM (initial view) ────────────────────────────
  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-50 to-purple-50 flex items-center justify-center p-4">
      <div className="bg-white rounded-2xl shadow-lg p-8 max-w-lg w-full">
        <div className="text-center mb-8">
          <img src="/logo-bci.png" alt="Better Choice Insurance Group" className="h-14 w-auto mx-auto mb-4" />
          <h1 className="text-2xl font-bold text-slate-900 mb-2">
            How did {info?.producer_name?.split(' ')[0]} do?
          </h1>
          <p className="text-slate-500">
            Thanks for choosing Better Choice Insurance Group, {info?.client_name}!
          </p>
        </div>

        <div className="flex justify-center space-x-3 mb-8">
          {[1, 2, 3, 4, 5].map((star) => (
            <button
              key={star}
              onClick={() => setSelectedRating(star)}
              className={`text-5xl transition-all duration-200 hover:scale-125 ${
                selectedRating && star <= selectedRating
                  ? 'drop-shadow-lg scale-110'
                  : 'opacity-30 grayscale'
              }`}
            >
              ⭐
            </button>
          ))}
        </div>

        {selectedRating && selectedRating <= 3 && (
          <div className="mb-6">
            <label className="block text-sm font-semibold text-slate-700 mb-2">
              We&apos;d love to know how we can improve:
            </label>
            <textarea
              value={feedback}
              onChange={(e) => setFeedback(e.target.value)}
              className="w-full border border-slate-300 rounded-xl px-4 py-3 text-sm focus:ring-2 focus:ring-purple-500 focus:border-purple-500 outline-none"
              rows={3}
              placeholder="Optional — your feedback helps us get better"
            />
          </div>
        )}

        {selectedRating && (
          <button
            onClick={() => handleSubmit()}
            className="w-full bg-gradient-to-r from-purple-600 to-indigo-600 text-white font-semibold py-3.5 rounded-xl text-lg hover:from-purple-700 hover:to-indigo-700 transition-all shadow-lg"
          >
            {selectedRating >= 4 ? '🌟 Submit & Share the Love!' : 'Submit Feedback'}
          </button>
        )}

        <div className="mt-8 pt-6 border-t border-slate-100 text-center">
          <p className="text-xs text-slate-400">
            Policy: {info?.policy_number} • {info?.carrier?.replace('_', ' ')}
          </p>
        </div>
      </div>
    </div>
  );
};

export default SurveyPage;
