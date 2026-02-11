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
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!id) return;
    loadSurveyInfo();
  }, [id]);

  useEffect(() => {
    if (urlRating && !submitted) {
      const r = parseInt(urlRating as string);
      if (r >= 1 && r <= 5) {
        setSelectedRating(r);
        // Auto-submit if they clicked a star in the email
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
        setRedirecting(true);
        setTimeout(() => {
          window.location.href = res.data.google_review_url;
        }, 2000);
      }
    } catch (err) {
      console.error('Submit failed:', err);
    }
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

  // 5-star submitted — redirecting to Google
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

  // Already submitted or just submitted (non-5-star)
  if (submitted) {
    return (
      <div className="min-h-screen bg-gradient-to-br from-slate-50 to-purple-50 flex items-center justify-center">
        <div className="bg-white rounded-2xl shadow-lg p-8 text-center max-w-md">
          <div className="text-5xl mb-4">🙏</div>
          <h1 className="text-2xl font-bold text-slate-900 mb-2">Thank You!</h1>
          <p className="text-slate-600">
            Your feedback helps us improve. We appreciate you choosing Better Choice Insurance!
          </p>
        </div>
      </div>
    );
  }

  // Rating form
  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-50 to-purple-50 flex items-center justify-center p-4">
      <div className="bg-white rounded-2xl shadow-lg p-8 max-w-lg w-full">
        {/* Header */}
        <div className="text-center mb-8">
          <div className="w-16 h-16 bg-gradient-to-br from-purple-600 to-indigo-600 rounded-2xl flex items-center justify-center mx-auto mb-4 shadow-lg">
            <span className="text-white font-bold text-2xl">BC</span>
          </div>
          <h1 className="text-2xl font-bold text-slate-900 mb-2">
            How did {info?.producer_name?.split(' ')[0]} do?
          </h1>
          <p className="text-slate-500">
            Thanks for choosing Better Choice Insurance, {info?.client_name}!
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

        {selectedRating && selectedRating < 5 && (
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
            {selectedRating === 5 ? '🌟 Submit & Share the Love!' : 'Submit Feedback'}
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
