import React, { useState, useEffect } from 'react';
import { useRouter } from 'next/router';
import axios from 'axios';

const API = process.env.NEXT_PUBLIC_API_URL || 'https://better-choice-api.onrender.com';

// Fallback IL Google Review URL — used only if the backend response
// is missing google_review_url. The backend routes TX-region customers
// to the Texas listing automatically based on Customer.state.
const GOOGLE_REVIEW_URL_FALLBACK = 'https://g.page/r/CcqT2a9FrSoXEBM/review';

const STAR_LABELS = ['', 'Very Unhappy', 'Unhappy', 'Neutral', 'Happy', 'Very Happy'];

export default function RenewalSurveyPage() {
  const router = useRouter();
  const { token } = router.query;

  const [loading, setLoading] = useState(true);
  const [survey, setSurvey] = useState<any>(null);
  const [questions, setQuestions] = useState<any[]>([]);
  const [nextQuestion, setNextQuestion] = useState<any>(null);
  const [responses, setResponses] = useState<Record<string, any>>({});
  const [isComplete, setIsComplete] = useState(false);
  const [alreadyCompleted, setAlreadyCompleted] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [currentAnswer, setCurrentAnswer] = useState<any>(null);
  const [multiSelect, setMultiSelect] = useState<string[]>([]);
  const [textInput, setTextInput] = useState('');
  const [phase, setPhase] = useState<'loading' | 'survey' | 'thank_you' | 'completed'>('loading');
  const [starHover, setStarHover] = useState(0);

  useEffect(() => {
    if (!token) return;
    loadSurvey();
  }, [token]);

  const loadSurvey = async () => {
    try {
      const res = await axios.get(`${API}/api/renewal-survey/take/${token}`);
      const data = res.data;
      if (data.completed) {
        setAlreadyCompleted(true);
        setSurvey(data);
        setPhase('completed');
      } else {
        setSurvey(data);
        setQuestions(data.questions || []);
        setNextQuestion(data.next_question);
        setResponses(data.responses || {});
        setIsComplete(data.is_complete);
        setPhase(data.is_complete ? 'thank_you' : 'survey');
      }
    } catch (e: any) {
      console.error(e);
    }
    setLoading(false);
  };

  const submitAnswer = async (questionId: string, answer: any) => {
    setSubmitting(true);
    try {
      const res = await axios.post(`${API}/api/renewal-survey/take/${token}/answer`, {
        question_id: questionId,
        answer: answer,
      });
      const data = res.data;
      setResponses(data.responses);
      setNextQuestion(data.next_question);
      // Carry forward the state-routed review URL from the answer
      // response — the backend includes it on every answer response so
      // it's available regardless of which question completed the survey.
      if (data.google_review_url) {
        setSurvey((prev: any) => ({ ...(prev || {}), google_review_url: data.google_review_url }));
      }
      setCurrentAnswer(null);
      setMultiSelect([]);
      setTextInput('');
      if (data.is_complete) {
        setIsComplete(true);
        setPhase('thank_you');
      }
    } catch (e: any) {
      console.error(e);
    }
    setSubmitting(false);
  };

  // Render star rating
  const renderStars = (q: any) => {
    const selected = currentAnswer as number || 0;
    return (
      <div className="flex flex-col items-center gap-4">
        <div className="flex gap-2">
          {[1, 2, 3, 4, 5].map(star => (
            <button
              key={star}
              onMouseEnter={() => setStarHover(star)}
              onMouseLeave={() => setStarHover(0)}
              onClick={() => { setCurrentAnswer(star); submitAnswer(q.id, star); }}
              disabled={submitting}
              className="text-5xl transition-transform hover:scale-110 disabled:opacity-50"
            >
              {star <= (starHover || selected) ? '⭐' : '☆'}
            </button>
          ))}
        </div>
        {(starHover || selected) > 0 && (
          <span className="text-sm text-slate-500">{STAR_LABELS[starHover || selected]}</span>
        )}
      </div>
    );
  };

  // Render yes/no
  const renderYesNo = (q: any) => (
    <div className="flex gap-4 justify-center">
      <button
        onClick={() => submitAnswer(q.id, true)}
        disabled={submitting}
        className="px-8 py-3 bg-emerald-500 text-white font-semibold rounded-xl hover:bg-emerald-600 transition-colors disabled:opacity-50 text-lg"
      >
        Yes
      </button>
      <button
        onClick={() => submitAnswer(q.id, false)}
        disabled={submitting}
        className="px-8 py-3 bg-slate-200 text-slate-700 font-semibold rounded-xl hover:bg-slate-300 transition-colors disabled:opacity-50 text-lg"
      >
        No
      </button>
    </div>
  );

  // Render single select
  const renderSingleSelect = (q: any) => (
    <div className="flex flex-col gap-3 max-w-md mx-auto">
      {q.options.map((opt: any) => (
        <button
          key={opt.value}
          onClick={() => submitAnswer(q.id, opt.value)}
          disabled={submitting}
          className="w-full px-5 py-3 text-left bg-white border-2 border-slate-200 rounded-xl hover:border-blue-400 hover:bg-blue-50 transition-all disabled:opacity-50 font-medium text-slate-700"
        >
          {opt.label}
        </button>
      ))}
    </div>
  );

  // Render multi select
  const renderMultiSelect = (q: any) => {
    const toggle = (val: string) => {
      if (val === 'none') {
        setMultiSelect(['none']);
      } else {
        setMultiSelect(prev => {
          const without = prev.filter(v => v !== 'none');
          return without.includes(val) ? without.filter(v => v !== val) : [...without, val];
        });
      }
    };
    return (
      <div className="flex flex-col gap-2 max-w-md mx-auto">
        {q.options.map((opt: any) => (
          <button
            key={opt.value}
            onClick={() => toggle(opt.value)}
            className={`w-full px-5 py-3 text-left border-2 rounded-xl transition-all font-medium ${
              multiSelect.includes(opt.value)
                ? 'border-blue-500 bg-blue-50 text-blue-700'
                : 'border-slate-200 bg-white text-slate-700 hover:border-slate-300'
            }`}
          >
            <span className="mr-2">{multiSelect.includes(opt.value) ? '✓' : '○'}</span>
            {opt.label}
          </button>
        ))}
        {multiSelect.length > 0 && (
          <button
            onClick={() => submitAnswer(q.id, multiSelect)}
            disabled={submitting}
            className="mt-3 px-6 py-3 bg-blue-600 text-white font-semibold rounded-xl hover:bg-blue-700 transition-colors disabled:opacity-50"
          >
            {submitting ? 'Saving...' : 'Continue'}
          </button>
        )}
      </div>
    );
  };

  // Render text input
  const renderText = (q: any) => (
    <div className="max-w-md mx-auto">
      <textarea
        value={textInput}
        onChange={e => setTextInput(e.target.value)}
        placeholder={q.placeholder || 'Your response...'}
        rows={3}
        className="w-full px-4 py-3 border-2 border-slate-200 rounded-xl focus:border-blue-400 focus:outline-none text-slate-700 resize-none"
      />
      <div className="flex gap-3 mt-3 justify-center">
        <button
          onClick={() => submitAnswer(q.id, textInput || '(no response)')}
          disabled={submitting}
          className="px-6 py-2.5 bg-blue-600 text-white font-semibold rounded-xl hover:bg-blue-700 transition-colors disabled:opacity-50"
        >
          {submitting ? 'Saving...' : 'Continue'}
        </button>
        <button
          onClick={() => submitAnswer(q.id, '(skipped)')}
          disabled={submitting}
          className="px-6 py-2.5 bg-slate-100 text-slate-500 font-medium rounded-xl hover:bg-slate-200 transition-colors disabled:opacity-50"
        >
          Skip
        </button>
      </div>
    </div>
  );

  const renderQuestion = (q: any) => {
    switch (q.type) {
      case 'stars': return renderStars(q);
      case 'yes_no': return renderYesNo(q);
      case 'single_select': return renderSingleSelect(q);
      case 'multi_select': return renderMultiSelect(q);
      case 'text': return renderText(q);
      default: return <div>Unknown question type</div>;
    }
  };

  // Progress
  const answeredCount = Object.keys(responses).length;
  const totalQuestions = questions.length || 1;
  const progress = Math.min((answeredCount / totalQuestions) * 100, 100);

  if (loading || phase === 'loading') {
    return (
      <div className="min-h-screen bg-gradient-to-br from-slate-50 to-blue-50 flex items-center justify-center">
        <div className="animate-spin h-8 w-8 border-4 border-blue-500 border-t-transparent rounded-full" />
      </div>
    );
  }

  if (phase === 'completed' || alreadyCompleted) {
    return (
      <div className="min-h-screen bg-gradient-to-br from-slate-50 to-blue-50 flex items-center justify-center p-4">
        <div className="bg-white rounded-2xl shadow-xl p-8 max-w-md w-full text-center">
          <div className="text-5xl mb-4">✅</div>
          <h1 className="text-2xl font-bold text-slate-900 mb-2">Thank You!</h1>
          <p className="text-slate-600">You've already completed this survey. We appreciate your feedback!</p>
        </div>
      </div>
    );
  }

  if (phase === 'thank_you') {
    const isHappy = (responses.happiness || 0) >= 4;
    return (
      <div className="min-h-screen bg-gradient-to-br from-slate-50 to-blue-50 flex items-center justify-center p-4">
        <div className="bg-white rounded-2xl shadow-xl p-8 max-w-lg w-full text-center">
          <div className="text-5xl mb-4">{isHappy ? '🎉' : '💙'}</div>
          <h1 className="text-2xl font-bold text-slate-900 mb-3">
            {isHappy ? 'Thank you for your feedback!' : 'Thank you — we hear you.'}
          </h1>
          {isHappy ? (
            <>
              <p className="text-slate-600 mb-6">
                We're glad you're happy with your coverage! We'll be reviewing your renewal rates proactively.
                If you have a moment, we'd love a Google review.
              </p>
              <a
                href={survey?.google_review_url || GOOGLE_REVIEW_URL_FALLBACK}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-block px-6 py-3 bg-blue-600 text-white font-semibold rounded-xl hover:bg-blue-700 transition-colors"
              >
                Leave a Google Review ⭐
              </a>
            </>
          ) : (
            <>
              <p className="text-slate-600 mb-4">
                Your feedback is important to us. {responses.wants_callback === 'call'
                  ? 'One of our agents will be calling you soon to review your options.'
                  : 'Our team will be reviewing your account and reaching out with options before your renewal.'}
              </p>
              <p className="text-sm text-slate-500">
                Better Choice Insurance Group<br />
                (847) 908-5665 · service@betterchoiceins.com
              </p>
            </>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-50 to-blue-50">
      {/* Header */}
      <div className="bg-white border-b border-slate-200 px-4 py-5">
        <div className="max-w-lg mx-auto text-center">
          <h1 className="text-lg font-bold text-slate-900">Better Choice Insurance</h1>
          <p className="text-sm text-slate-500 mt-1">Renewal Survey{survey?.carrier ? ` · ${(survey.carrier || '').replace('_', ' ').replace(/\b\w/g, (c: string) => c.toUpperCase())}` : ''}</p>
          {survey?.customer_name && (
            <p className="text-xs text-slate-400 mt-0.5">
              {survey.customer_name}{survey.renewal_date ? ` · Renews ${new Date(survey.renewal_date).toLocaleDateString('en-US', { month: 'long', day: 'numeric', year: 'numeric' })}` : ''}
            </p>
          )}
        </div>
      </div>

      {/* Progress bar */}
      <div className="max-w-lg mx-auto px-4 mt-4">
        <div className="h-1.5 bg-slate-200 rounded-full overflow-hidden">
          <div className="h-full bg-blue-500 rounded-full transition-all duration-500" style={{ width: `${progress}%` }} />
        </div>
        <p className="text-[10px] text-slate-400 mt-1 text-right">
          {answeredCount} of {totalQuestions}
        </p>
      </div>

      {/* Question */}
      {nextQuestion && (
        <div className="max-w-lg mx-auto px-4 mt-8">
          <div className="bg-white rounded-2xl shadow-lg p-8">
            <h2 className="text-xl font-semibold text-slate-900 text-center mb-8">
              {nextQuestion.text}
            </h2>
            {renderQuestion(nextQuestion)}
          </div>
        </div>
      )}

      {/* Footer */}
      <div className="max-w-lg mx-auto px-4 mt-8 pb-8 text-center">
        <p className="text-xs text-slate-400">
          Better Choice Insurance Group · (847) 908-5665<br />
          300 Cardinal Dr Suite 220, Saint Charles, IL 60175
        </p>
      </div>
    </div>
  );
}
