// Survey page for customer-keyed ratings (ID card emails, future touchpoints).
// Mirrors /survey/[id].tsx but routes via customer_id + source params so we
// don't need a sale_id to collect a rating.
import React, { useEffect, useState } from 'react';
import { useRouter } from 'next/router';
import api from '../../../lib/api';
import GoogleAnalytics from '../../../components/GoogleAnalytics';

// Fallback IL Google Review URL — only used if the backend response
// is missing google_review_url. For TX-region customers the backend
// returns the Texas listing based on Customer.state.
const GOOGLE_REVIEW_URL_FALLBACK = 'https://g.page/r/CcqT2a9FrSoXEBM/review';

const CustomerSurveyPage = () => {
  const router = useRouter();
  const { id, rating: urlRating, source: urlSource } = router.query;
  const [info, setInfo] = useState<any>(null);
  const [selectedRating, setSelectedRating] = useState<number | null>(null);
  const [feedback, setFeedback] = useState('');
  const [reviewUrl, setReviewUrl] = useState<string>(GOOGLE_REVIEW_URL_FALLBACK);
  const [phase, setPhase] = useState<
    'loading' | 'error' | 'rate' | 'redirecting' | 'feedback_form' | 'feedback_sent' | 'thankyou'
  >('loading');

  const [feedbackName, setFeedbackName] = useState('');
  const [feedbackEmail, setFeedbackEmail] = useState('');
  const [feedbackMessage, setFeedbackMessage] = useState('');
  const [sendingFeedback, setSendingFeedback] = useState(false);

  const source = (urlSource as string) || 'id_card';

  useEffect(() => {
    if (!router.isReady || !id) return;
    loadSurveyInfo();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [router.isReady, id]);

  useEffect(() => {
    if (urlRating && info && phase === 'rate') {
      const r = parseInt(urlRating as string);
      if (r >= 1 && r <= 5) {
        setSelectedRating(r);
        handleSubmit(r);
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [urlRating, info, phase]);

  const loadSurveyInfo = async () => {
    try {
      const res = await api.get(`/api/survey/info-by-customer/${id}`, { params: { source } });
      setInfo(res.data);
      if (res.data.already_submitted) {
        const rFromUrl = urlRating ? parseInt(urlRating as string) : 0;
        if (rFromUrl >= 4) {
          // Fire a no-op submit to get the state-routed URL for this customer
          let urlToUse = GOOGLE_REVIEW_URL_FALLBACK;
          try {
            const submitRes = await api.post('/api/survey/submit-by-customer', null, {
              params: { customer_id: id, rating: rFromUrl, source },
            });
            if (submitRes.data?.google_review_url) {
              urlToUse = submitRes.data.google_review_url;
              setReviewUrl(urlToUse);
            }
          } catch { /* fall through */ }
          setPhase('redirecting');
          setTimeout(() => { window.location.href = urlToUse; }, 2500);
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
      const res = await api.post('/api/survey/submit-by-customer', null, {
        params: { customer_id: id, rating: r, source, feedback: feedback || undefined },
      });
      const urlFromApi = res.data?.google_review_url || GOOGLE_REVIEW_URL_FALLBACK;
      setReviewUrl(urlFromApi);
      if (r >= 4) {
        setPhase('redirecting');
        setTimeout(() => { window.location.href = urlFromApi; }, 2500);
      } else {
        setFeedbackName(info?.client_name || '');
        setPhase('feedback_form');
      }
    } catch (err: any) {
      if (r >= 4) {
        setPhase('redirecting');
        setTimeout(() => { window.location.href = reviewUrl; }, 2500);
      } else {
        setFeedbackName(info?.client_name || '');
        setPhase('feedback_form');
      }
    }
  };

  const handleSendFeedback = async () => {
    if (!feedbackMessage.trim()) return;
    setSendingFeedback(true);
    try {
      await api.post('/api/survey/feedback-by-customer', {
        customer_id: parseInt(id as string),
        name: feedbackName,
        email: feedbackEmail,
        message: feedbackMessage,
        rating: selectedRating,
        source,
      });
    } catch (err) {
      const subject = encodeURIComponent(
        `Customer Feedback - ${feedbackName || info?.client_name || 'Customer'} (${selectedRating} star)`
      );
      const body = encodeURIComponent(
        `Name: ${feedbackName || info?.client_name || ''}\n` +
        `Email: ${feedbackEmail}\n` +
        `Rating: ${selectedRating} out of 5 stars\n\n` +
        `Feedback:\n${feedbackMessage}\n`
      );
      window.open(`mailto:service@betterchoiceins.com?subject=${subject}&body=${body}`, '_self');
    }
    setPhase('feedback_sent');
  };

  if (phase === 'loading') {
    return (
      <div className="min-h-screen bg-gradient-to-br from-slate-50 to-purple-50 flex items-center justify-center">
        <div className="text-slate-500 animate-pulse">Loading...</div>
      </div>
    );
  }

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

  if (phase === 'redirecting') {
    return (
      <div className="min-h-screen bg-gradient-to-br from-slate-50 to-blue-50 flex items-center justify-center p-4">
        <div className="bg-white rounded-2xl shadow-xl p-8 text-center max-w-md w-full">
          <img src="/carrier-logos/bci_logo_color.png" alt="Better Choice Insurance Group" className="h-10 w-auto mx-auto mb-5" />
          <div className="text-5xl mb-3">🌟</div>
          <h1 className="text-2xl font-bold text-slate-900 mb-2">Thank you so much!</h1>
          <p className="text-sm text-slate-600 mb-4 leading-relaxed">
            We&apos;re thrilled you had a great experience with Better Choice Insurance.
          </p>
          <p className="text-sm text-emerald-700 font-semibold mb-4">
            Redirecting you to leave a Google review...
          </p>
          <div className="animate-spin w-6 h-6 border-2 border-emerald-600 border-t-transparent rounded-full mx-auto mb-5"></div>
          <a href={reviewUrl} className="text-xs text-emerald-600 hover:underline font-medium">
            Click here if not redirected automatically
          </a>
        </div>
      </div>
    );
  }

  if (phase === 'feedback_form') {
    return (
      <div className="min-h-screen bg-gradient-to-br from-slate-50 to-blue-50 flex items-center justify-center p-4 py-8">
        <div className="bg-white rounded-2xl shadow-xl p-6 sm:p-8 max-w-lg w-full">
          <div className="text-center mb-6">
            <img src="/carrier-logos/bci_logo_color.png" alt="Better Choice Insurance Group" className="h-12 w-auto mx-auto mb-5" />
            <h1 className="text-2xl font-bold text-slate-900 mb-2 leading-tight">
              We want to make it right
            </h1>
            <p className="text-sm text-slate-600 leading-relaxed">
              We&apos;re sorry your experience wasn&apos;t what you hoped for. Tell us what happened and we&apos;ll follow up personally.
            </p>
          </div>
          <div className="space-y-3">
            <div>
              <label className="block text-xs font-semibold text-slate-700 mb-1 uppercase tracking-wide">Name</label>
              <input type="text" value={feedbackName} onChange={(e) => setFeedbackName(e.target.value)}
                className="w-full border border-slate-200 rounded-lg px-3.5 py-2.5 text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none bg-slate-50 focus:bg-white transition-colors"
                style={{ color: '#0f172a' }}
                placeholder="Your full name" />
            </div>
            <div>
              <label className="block text-xs font-semibold text-slate-700 mb-1 uppercase tracking-wide">Email</label>
              <input type="email" value={feedbackEmail} onChange={(e) => setFeedbackEmail(e.target.value)}
                className="w-full border border-slate-200 rounded-lg px-3.5 py-2.5 text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none bg-slate-50 focus:bg-white transition-colors"
                style={{ color: '#0f172a' }}
                placeholder="So we can reach back out" />
            </div>
            <div>
              <label className="block text-xs font-semibold text-slate-700 mb-1 uppercase tracking-wide">
                What could we have done better?
              </label>
              <textarea value={feedbackMessage} onChange={(e) => setFeedbackMessage(e.target.value)}
                className="w-full border border-slate-200 rounded-lg px-3.5 py-2.5 text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none bg-slate-50 focus:bg-white transition-colors resize-none"
                style={{ color: '#0f172a' }}
                rows={5}
                placeholder="We take every response seriously — please be as specific as you can." />
            </div>
            <button onClick={handleSendFeedback} disabled={!feedbackMessage.trim() || sendingFeedback}
              className={`w-full font-semibold py-3 rounded-lg text-sm transition-all ${
                feedbackMessage.trim() && !sendingFeedback
                  ? 'bg-slate-900 text-white hover:bg-slate-800 shadow-md'
                  : 'bg-slate-100 text-slate-400 cursor-not-allowed'
              }`}>
              {sendingFeedback ? 'Sending...' : 'Send Feedback'}
            </button>
          </div>
        </div>
      </div>
    );
  }

  if (phase === 'feedback_sent') {
    return (
      <div className="min-h-screen bg-gradient-to-br from-slate-50 to-blue-50 flex items-center justify-center p-4">
        <div className="bg-white rounded-2xl shadow-xl p-8 text-center max-w-md w-full">
          <img src="/carrier-logos/bci_logo_color.png" alt="Better Choice Insurance Group" className="h-10 w-auto mx-auto mb-5" />
          <div className="w-16 h-16 rounded-full bg-emerald-100 flex items-center justify-center mx-auto mb-4">
            <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="#059669" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
              <polyline points="20 6 9 17 4 12"/>
            </svg>
          </div>
          <h1 className="text-2xl font-bold text-slate-900 mb-2">Thank you for your feedback</h1>
          <p className="text-sm text-slate-600 leading-relaxed mb-4">
            We take your concerns seriously and someone from our team will reach out to you personally to make things right.
          </p>
          <p className="text-xs text-slate-500">— The Better Choice Insurance Team</p>
        </div>
      </div>
    );
  }

  if (phase === 'thankyou') {
    return (
      <div className="min-h-screen bg-gradient-to-br from-slate-50 to-blue-50 flex items-center justify-center p-4">
        <GoogleAnalytics />
        <div className="bg-white rounded-2xl shadow-xl p-8 text-center max-w-md w-full">
          <img src="/carrier-logos/bci_logo_color.png" alt="Better Choice Insurance Group" className="h-10 w-auto mx-auto mb-5" />
          <div className="text-5xl mb-3">🙏</div>
          <h1 className="text-2xl font-bold text-slate-900 mb-2">Thank you!</h1>
          <p className="text-sm text-slate-600 leading-relaxed">
            Your feedback helps us improve. We appreciate you choosing Better Choice Insurance Group.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-50 to-blue-50 flex items-center justify-center p-4 py-8">
      <div className="bg-white rounded-2xl shadow-xl p-6 sm:p-8 max-w-lg w-full">
        <div className="text-center mb-6">
          <img src="/carrier-logos/bci_logo_color.png" alt="Better Choice Insurance Group" className="h-12 w-auto mx-auto mb-5" />
          <h1 className="text-2xl font-bold text-slate-900 mb-2">How are we doing?</h1>
          <p className="text-sm text-slate-600">
            Thanks for choosing Better Choice{info?.client_name && info.client_name !== 'Customer' ? `, ${info.client_name}` : ''}!
          </p>
        </div>
        <div className="flex justify-center space-x-2 sm:space-x-3 mb-6">
          {[1, 2, 3, 4, 5].map((star) => (
            <button key={star} onClick={() => setSelectedRating(star)}
              className={`text-4xl sm:text-5xl transition-all duration-200 hover:scale-125 ${
                selectedRating && star <= selectedRating ? 'drop-shadow-md scale-110' : 'opacity-30 grayscale'
              }`}>
              ⭐
            </button>
          ))}
        </div>
        {selectedRating && selectedRating <= 3 && (
          <div className="mb-4">
            <label className="block text-xs font-semibold text-slate-700 mb-1 uppercase tracking-wide">
              How can we improve?
            </label>
            <textarea value={feedback} onChange={(e) => setFeedback(e.target.value)}
              className="w-full border border-slate-200 rounded-lg px-3.5 py-2.5 text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none bg-slate-50 focus:bg-white transition-colors resize-none"
              style={{ color: '#0f172a' }}
              rows={3} placeholder="Optional — your feedback helps us get better" />
          </div>
        )}
        {selectedRating && (
          <button onClick={() => handleSubmit()}
            className="w-full bg-slate-900 text-white font-semibold py-3 rounded-lg text-sm hover:bg-slate-800 transition-all shadow-md">
            {selectedRating >= 4 ? 'Submit & Share a Review' : 'Submit Feedback'}
          </button>
        )}
      </div>
    </div>
  );
};

export default CustomerSurveyPage;
