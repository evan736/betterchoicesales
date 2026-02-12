import React, { useEffect, useState } from 'react';
import { useRouter } from 'next/router';
import api from '../../lib/api';

const AGENCY_EMAIL = 'evan@betterchoiceins.com';
const AGENCY_PHONE = '847-908-5665';

const SurveyPage = () => {
  const router = useRouter();
  const { id, rating: urlRating } = router.query;
  const [info, setInfo] = useState<any>(null);
  const [selectedRating, setSelectedRating] = useState<number | null>(null);
  const [submitted, setSubmitted] = useState(false);
  const [redirecting, setRedirecting] = useState(false);
  const [showFeedbackForm, setShowFeedbackForm] = useState(false);
  const [feedbackMessage, setFeedbackMessage] = useState('');
  const [feedbackEmail, setFeedbackEmail] = useState('');
  const [feedbackSent, setFeedbackSent] = useState(false);
  const [sendingFeedback, setSendingFeedback] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!id) return;
    loadSurveyInfo();
  }, [id]);

  useEffect(() => {
    if (urlRating && !submitted && info) {
      const r = parseInt(urlRating as string);
      if (r >= 1 && r <= 5) {
        setSelectedRating(r);
        handleSubmit(r);
      }
    }
  }, [urlRating, info]);

  const loadSurveyInfo = async () => {
    try {
      const res = await api.get(`/api/survey/info/${id}`);
      setInfo(res.data);
      if (res.data.already_submitted) {
        setSubmitted(true);
      }
    } catch (err) {
      setError('Survey not found');
    } finally {
      setLoading(false);
    }
  };

  const handleSubmit = async (rating?: number) => {
    const r = rating || selectedRating;
    if (!r || !id) return;

    try {
      const res = await api.post('/api/survey/submit', null, {
        params: { sale_id: id, rating: r },
      });
      setSubmitted(true);

      if (r >= 4 && res.data.redirect_to_google && res.data.google_review_url) {
        setRedirecting(true);
        setTimeout(() => {
          window.location.href = res.data.google_review_url;
        }, 2000);
      } else if (r <= 3) {
        setShowFeedbackForm(true);
      }
    } catch (err) {
      console.error('Submit failed:', err);
    }
  };

  const handleSendFeedback = async () => {
    if (!feedbackMessage.trim()) return;
    setSendingFeedback(true);

    try {
      await api.post('/api/survey/feedback', {
        sale_id: parseInt(id as string),
        message: feedbackMessage,
        email: feedbackEmail || undefined,
        rating: selectedRating,
      });
      setFeedbackSent(true);
    } catch (err) {
      // Fallback: open mailto link
      const subject = encodeURIComponent(
        `Feedback - ${info?.client_name || 'Customer'} (${selectedRating} star)`
      );
      const body = encodeURIComponent(
        `Rating: ${selectedRating}/5\nPolicy: ${info?.policy_number || 'N/A'}\nCarrier: ${info?.carrier || 'N/A'}\n\n${feedbackMessage}\n\nReply to: ${feedbackEmail || 'not provided'}`
      );
      window.location.href = `mailto:${AGENCY_EMAIL}?subject=${subject}&body=${body}`;
      setFeedbackSent(true);
    } finally {
      setSendingFeedback(false);
    }
  };

  if (loading) {
    return (
      <div className="min-h-screen bg-gradient-to-br from-slate-50 to-blue-50 flex items-center justify-center">
        <div className="text-slate-500 animate-pulse">Loading...</div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="min-h-screen bg-gradient-to-br from-slate-50 to-blue-50 flex items-center justify-center">
        <div className="bg-white rounded-2xl shadow-lg p-8 text-center max-w-md">
          <div className="text-4xl mb-4">😕</div>
          <h1 className="text-xl font-bold text-slate-900 mb-2">Survey Not Found</h1>
          <p className="text-slate-500">This survey link may have expired or is invalid.</p>
        </div>
      </div>
    );
  }

  // 4-5 star — redirecting to Google
  if (submitted && redirecting) {
    return (
      <div className="min-h-screen bg-gradient-to-br from-green-50 to-emerald-50 flex items-center justify-center">
        <div className="bg-white rounded-2xl shadow-lg p-8 text-center max-w-md">
          <div className="text-5xl mb-4">🌟</div>
          <h1 className="text-2xl font-bold text-slate-900 mb-2">Thank you so much!</h1>
          <p className="text-slate-600 mb-4">
            We&apos;re thrilled you had a great experience with {info?.producer_name}!
          </p>
          <p className="text-green-700 font-semibold mb-2">
            Redirecting you to leave a Google review...
          </p>
          <div className="animate-spin w-6 h-6 border-2 border-green-600 border-t-transparent rounded-full mx-auto"></div>
        </div>
      </div>
    );
  }

  // 1-3 star — feedback form
  if (submitted && showFeedbackForm && !feedbackSent) {
    return (
      <div className="min-h-screen bg-gradient-to-br from-slate-50 to-blue-50 flex items-center justify-center p-4">
        <div className="bg-white rounded-2xl shadow-lg p-8 max-w-lg w-full">
          <div className="text-center mb-6">
            <img src="/logo-bci.png" alt="Better Choice Insurance Group" className="h-12 w-auto mx-auto mb-4" />
            <h1 className="text-2xl font-bold text-slate-900 mb-2">We Want to Make It Right</h1>
            <p className="text-slate-500">
              We&apos;re sorry your experience wasn&apos;t 100%. Your feedback helps us improve — please let us know what happened.
            </p>
          </div>

          {/* Rating display */}
          <div className="flex justify-center space-x-1 mb-6">
            {[1, 2, 3, 4, 5].map((star) => (
              <span
                key={star}
                className={`text-3xl ${
                  selectedRating && star <= selectedRating
                    ? 'opacity-100'
                    : 'opacity-20 grayscale'
                }`}
              >
                ⭐
              </span>
            ))}
          </div>

          {/* Feedback form */}
          <div className="space-y-4">
            <div>
              <label className="block text-sm font-semibold text-slate-700 mb-1.5">
                What could we have done better? <span className="text-red-400">*</span>
              </label>
              <textarea
                value={feedbackMessage}
                onChange={(e) => setFeedbackMessage(e.target.value)}
                className="w-full border border-slate-300 rounded-xl px-4 py-3 text-sm focus:ring-2 focus:ring-blue-400 focus:border-blue-400 resize-none"
                rows={4}
                placeholder="Please share any details about your experience..."
                autoFocus
              />
            </div>

            <div>
              <label className="block text-sm font-semibold text-slate-700 mb-1.5">
                Your email <span className="text-slate-400 font-normal">(so we can follow up)</span>
              </label>
              <input
                type="email"
                value={feedbackEmail}
                onChange={(e) => setFeedbackEmail(e.target.value)}
                className="w-full border border-slate-300 rounded-xl px-4 py-3 text-sm focus:ring-2 focus:ring-blue-400 focus:border-blue-400"
                placeholder="your@email.com"
              />
            </div>

            <button
              onClick={handleSendFeedback}
              disabled={!feedbackMessage.trim() || sendingFeedback}
              className="w-full bg-[#1a2b5f] text-white font-semibold py-3.5 rounded-xl text-lg hover:bg-[#162249] transition-all shadow-lg disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {sendingFeedback ? 'Sending...' : 'Send Feedback'}
            </button>
          </div>

          <div className="mt-6 pt-4 border-t border-slate-100 text-center">
            <p className="text-sm text-slate-500">
              You can also reach us directly at{' '}
              <a href={`tel:${AGENCY_PHONE.replace(/-/g, '')}`} className="text-[#2cb5e8] font-semibold hover:underline">
                {AGENCY_PHONE}
              </a>
            </p>
          </div>
        </div>
      </div>
    );
  }

  // Feedback sent thank you
  if (feedbackSent) {
    return (
      <div className="min-h-screen bg-gradient-to-br from-slate-50 to-blue-50 flex items-center justify-center p-4">
        <div className="bg-white rounded-2xl shadow-lg p-8 text-center max-w-md">
          <div className="text-5xl mb-4">💬</div>
          <h1 className="text-2xl font-bold text-slate-900 mb-2">Thank You for Your Feedback</h1>
          <p className="text-slate-600 mb-4">
            We take your feedback seriously. Someone from our team will review your comments and follow up if needed.
          </p>
          <p className="text-sm text-slate-500">
            Need immediate help? Call us at{' '}
            <a href={`tel:${AGENCY_PHONE.replace(/-/g, '')}`} className="text-[#2cb5e8] font-semibold hover:underline">
              {AGENCY_PHONE}
            </a>
          </p>
        </div>
      </div>
    );
  }

  // Already submitted (revisit)
  if (submitted && !showFeedbackForm) {
    return (
      <div className="min-h-screen bg-gradient-to-br from-slate-50 to-blue-50 flex items-center justify-center">
        <div className="bg-white rounded-2xl shadow-lg p-8 text-center max-w-md">
          <div className="text-5xl mb-4">🙏</div>
          <h1 className="text-2xl font-bold text-slate-900 mb-2">Thank You!</h1>
          <p className="text-slate-600">
            Your feedback has already been recorded. We appreciate you choosing Better Choice Insurance Group!
          </p>
        </div>
      </div>
    );
  }

  // Rating form (manual visit, no rating in URL)
  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-50 to-blue-50 flex items-center justify-center p-4">
      <div className="bg-white rounded-2xl shadow-lg p-8 max-w-lg w-full">
        {/* Header */}
        <div className="text-center mb-8">
          <img src="/logo-bci.png" alt="Better Choice Insurance Group" className="h-14 w-auto mx-auto mb-4" />
          <h1 className="text-2xl font-bold text-slate-900 mb-2">
            How did {info?.producer_name?.split(' ')[0]} do?
          </h1>
          <p className="text-slate-500">
            Thanks for choosing Better Choice Insurance Group, {info?.client_name}!
          </p>
        </div>

        {/* Star Rating */}
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

        {selectedRating && (
          <button
            onClick={() => handleSubmit()}
            className="w-full bg-[#1a2b5f] text-white font-semibold py-3.5 rounded-xl text-lg hover:bg-[#162249] transition-all shadow-lg"
          >
            {selectedRating >= 4 ? '🌟 Submit & Share the Love!' : 'Submit Rating'}
          </button>
        )}

        {/* Policy info subtle footer */}
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
