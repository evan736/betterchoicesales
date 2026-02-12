import React, { useEffect, useState } from 'react';
import { useRouter } from 'next/router';
import api from '../../lib/api';

const SurveyPage = () => {
  const router = useRouter();
  const { id, rating: urlRating } = router.query;
  const [info, setInfo] = useState<any>(null);
  const [selectedRating, setSelectedRating] = useState<number | null>(null);
  const [feedback, setFeedback] = useState('');
  const [submitted, setSubmitted] = useState(false);
  const [redirecting, setRedirecting] = useState(false);
  const [showFeedbackForm, setShowFeedbackForm] = useState(false);
  const [feedbackSent, setFeedbackSent] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Feedback form fields
  const [feedbackName, setFeedbackName] = useState('');
  const [feedbackEmail, setFeedbackEmail] = useState('');
  const [feedbackMessage, setFeedbackMessage] = useState('');

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
        params: { sale_id: id, rating: r, feedback: feedback || undefined },
      });
      setSubmitted(true);

      if (res.data.redirect_to_google && res.data.google_review_url) {
        // 4-5 stars -> Google Review
        setRedirecting(true);
        setTimeout(() => {
          window.location.href = res.data.google_review_url;
        }, 2500);
      } else if (res.data.show_feedback_form) {
        // 1-3 stars -> show feedback form
        setShowFeedbackForm(true);
        if (info?.client_name) {
          setFeedbackName(info.client_name);
        }
      }
    } catch (err) {
      console.error('Submit failed:', err);
    }
  };

  const handleSendFeedback = () => {
    const subject = encodeURIComponent(
      `Feedback - ${feedbackName || info?.client_name || 'Customer'} (${selectedRating} star)`
    );
    const body = encodeURIComponent(
      `Name: ${feedbackName || info?.client_name || ''}\n` +
      `Email: ${feedbackEmail}\n` +
      `Policy: ${info?.policy_number || ''}\n` +
      `Rating: ${selectedRating} out of 5 stars\n\n` +
      `Feedback:\n${feedbackMessage}\n`
    );
    window.location.href = `mailto:evan@betterchoiceins.com?subject=${subject}&body=${body}`;
    setFeedbackSent(true);
  };

  if (loading) {
    return (
      <div className="min-h-screen bg-gradient-to-br from-slate-50 to-purple-50 flex items-center justify-center">
        <div className="text-slate-500 animate-pulse">Loading...</div>
      </div>
    );
  }

  if (error) {
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

  // 4-5 star submitted — redirecting to Google
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

  // 1-3 star submitted — show detailed feedback form
  if (submitted && showFeedbackForm && !feedbackSent) {
    return (
      <div className="min-h-screen bg-gradient-to-br from-slate-50 to-blue-50 flex items-center justify-center p-4">
        <div className="bg-white rounded-2xl shadow-lg p-8 max-w-lg w-full">
          <div className="text-center mb-6">
            <img src="/logo-bci.png" alt="Better Choice Insurance Group" className="h-14 w-auto mx-auto mb-4" />
            <div className="text-4xl mb-3">💬</div>
            <h1 className="text-2xl font-bold text-slate-900 mb-2">
              We want to make it right
            </h1>
            <p className="text-slate-500">
              We&apos;re sorry your experience wasn&apos;t 100%.
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
                className="w-full border border-slate-300 rounded-xl px-4 py-3 text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                placeholder="Your full name"
              />
            </div>

            <div>
              <label className="block text-sm font-semibold text-slate-700 mb-1">Your Email</label>
              <input
                type="email"
                value={feedbackEmail}
                onChange={(e) => setFeedbackEmail(e.target.value)}
                className="w-full border border-slate-300 rounded-xl px-4 py-3 text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
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
                className="w-full border border-slate-300 rounded-xl px-4 py-3 text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                rows={5}
                placeholder="Please tell us about your experience — we take every response seriously and will follow up personally."
              />
            </div>

            <button
              onClick={handleSendFeedback}
              disabled={!feedbackMessage.trim()}
              className={`w-full font-semibold py-3.5 rounded-xl text-lg transition-all shadow-lg ${
                feedbackMessage.trim()
                  ? 'bg-gradient-to-r from-blue-600 to-indigo-600 text-white hover:from-blue-700 hover:to-indigo-700'
                  : 'bg-slate-200 text-slate-400 cursor-not-allowed'
              }`}
            >
              ✉️ Send Feedback
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

  // Feedback sent confirmation
  if (feedbackSent) {
    return (
      <div className="min-h-screen bg-gradient-to-br from-slate-50 to-blue-50 flex items-center justify-center">
        <div className="bg-white rounded-2xl shadow-lg p-8 text-center max-w-md">
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

  // Already submitted (no special flow needed)
  if (submitted && !showFeedbackForm) {
    return (
      <div className="min-h-screen bg-gradient-to-br from-slate-50 to-purple-50 flex items-center justify-center">
        <div className="bg-white rounded-2xl shadow-lg p-8 text-center max-w-md">
          <div className="text-5xl mb-4">🙏</div>
          <h1 className="text-2xl font-bold text-slate-900 mb-2">Thank You!</h1>
          <p className="text-slate-600">
            Your feedback helps us improve. We appreciate you choosing Better Choice Insurance Group!
          </p>
        </div>
      </div>
    );
  }

  // Rating form (initial view)
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
              className="w-full border border-slate-300 rounded-xl px-4 py-3 text-sm focus:ring-2 focus:ring-purple-500 focus:border-purple-500"
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
