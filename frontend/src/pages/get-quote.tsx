import React, { useState, useEffect } from 'react';
import Head from 'next/head';
import { useRouter } from 'next/router';
import { Shield, Phone, Clock, DollarSign, Users, CheckCircle, Star, ArrowRight, ChevronDown } from 'lucide-react';

// Public landing page — theme classes removed via useEffect

const CARRIERS = [
  { name: 'Travelers', logo: '/carrier-logos/travelers.png' },
  { name: 'Progressive', logo: '/carrier-logos/progressive.png' },
  { name: 'Safeco', logo: '/carrier-logos/safeco.png' },
  { name: 'National General', logo: '/carrier-logos/national_general.png' },
  { name: 'Grange', logo: '/carrier-logos/grange.png' },
  { name: 'GEICO', logo: '/carrier-logos/geico.png' },
  { name: 'Openly', logo: '/carrier-logos/openly.png' },
  { name: 'Bristol West', logo: '/carrier-logos/bristol_west.png' },
  { name: 'Hippo', logo: '/carrier-logos/hippo.png' },
  { name: 'Branch', logo: '/carrier-logos/branch.png' },
  { name: 'Steadily', logo: '/carrier-logos/steadily.png' },
  { name: 'Integrity', logo: '/carrier-logos/integrity.png' },
  { name: 'Clearcover', logo: '/carrier-logos/clearcover.png' },
  { name: 'American Modern', logo: '/carrier-logos/american_modern.png' },
  { name: 'Universal Property', logo: '/carrier-logos/universal_property.png' },
  { name: 'CoverTree', logo: '/carrier-logos/covertree.png' },
];

const PHONE = '(847) 908-5665';
const PHONE_DIGITS = '8479085665';
const EMAIL = 'service@betterchoiceins.com';

// Video section removed — no longer needed

export default function GetQuotePage() {
  const router = useRouter();
  const { name, type, carrier, xdate, utm_campaign } = router.query;
  const firstName = (name as string) || '';
  const policyType = ((type as string) || 'insurance').replace(/_/g, ' ');
  const currentCarrier = (carrier as string) || '';
  const renewalDate = (xdate as string) || '';

  const [formData, setFormData] = useState({ name: '', email: '', phone: '', message: '' });
  const [submitted, setSubmitted] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  // Strip dark theme classes on this public page
  useEffect(() => {
    const body = document.body;
    const savedClasses = body.className;
    body.classList.remove('mission-control', 'sakura-pink', 'apple-clean', 'blue-white', 'true-black');
    return () => { body.className = savedClasses; };
  }, []);

  useEffect(() => {
    if (firstName) setFormData(prev => ({ ...prev, name: firstName }));
  }, [firstName]);

  const handleSubmit = async () => {
    if (!formData.name || !formData.phone) return;
    setSubmitting(true);
    try {
      // Send to backend as a requote request
      const API = process.env.NEXT_PUBLIC_API_URL || 'https://better-choice-api.onrender.com';
      await fetch(`${API}/api/campaigns/landing-lead`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          ...formData,
          policy_type: policyType,
          current_carrier: currentCarrier,
          renewal_date: renewalDate,
          utm_campaign: utm_campaign || '',
          source: 'requote_landing_page',
        }),
      });
      setSubmitted(true);
    } catch (e) {
      // Still show success — we'll follow up manually
      setSubmitted(true);
    }
    setSubmitting(false);
  };

  return (
    <>
      <Head>
        <title>Get Your Free Quote Comparison | Better Choice Insurance</title>
        <meta name="description" content="Compare rates from 15+ carriers in minutes. Free, no-obligation insurance quote comparison from Better Choice Insurance." />
        <link href="https://fonts.googleapis.com/css2?family=DM+Sans:ital,opsz,wght@0,9..40,300;0,9..40,400;0,9..40,500;0,9..40,600;0,9..40,700;0,9..40,800&family=Playfair+Display:wght@600;700;800&display=swap" rel="stylesheet" />
      </Head>

      <div className="get-quote-page" style={{ margin: 0, padding: 0, background: '#fafbfc', fontFamily: "'DM Sans', sans-serif", color: '#1a1a2e', minHeight: '100vh' }}>

        {/* ═══ HERO ═══ */}
        <section style={{
          background: 'linear-gradient(145deg, #0a1628 0%, #132042 40%, #1a3a5c 100%)',
          position: 'relative', overflow: 'hidden', padding: '0',
        }}>
          {/* Subtle grid overlay */}
          <div style={{
            position: 'absolute', inset: 0, opacity: 0.04,
            backgroundImage: 'linear-gradient(rgba(255,255,255,.1) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,.1) 1px, transparent 1px)',
            backgroundSize: '60px 60px',
          }} />
          {/* Gradient orb */}
          <div style={{
            position: 'absolute', top: '-200px', right: '-100px', width: '600px', height: '600px',
            background: 'radial-gradient(circle, rgba(59,130,246,0.15) 0%, transparent 70%)',
            borderRadius: '50%',
          }} />

          <div style={{ maxWidth: '1100px', margin: '0 auto', padding: '48px 24px 56px', position: 'relative', zIndex: 1 }}>
            {/* Top bar */}
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '48px' }}>
              <img src="/carrier-logos/bci_header_white.png" alt="Better Choice Insurance" style={{ height: '36px' }} />
              <a href={`tel:${PHONE_DIGITS}`} style={{
                color: '#93c5fd', fontSize: '15px', fontWeight: 600, textDecoration: 'none',
                display: 'flex', alignItems: 'center', gap: '6px',
              }}>
                <Phone size={16} /> {PHONE}
              </a>
            </div>

            <div style={{ display: 'flex', gap: '48px', alignItems: 'center', flexWrap: 'wrap' as const }}>
              {/* Left: Copy */}
              <div style={{ flex: '1 1 480px', minWidth: '300px' }}>
                {firstName && (
                  <p style={{ color: '#60a5fa', fontSize: '15px', fontWeight: 600, margin: '0 0 12px', letterSpacing: '0.5px' }}>
                    {firstName}, your {policyType} renewal is coming up
                  </p>
                )}
                <h1 style={{
                  fontFamily: "'Playfair Display', serif", color: '#ffffff',
                  fontSize: 'clamp(32px, 5vw, 48px)', lineHeight: 1.15, fontWeight: 700,
                  margin: '0 0 20px',
                }}>
                  Stop overpaying for <br />
                  <span style={{ color: '#60a5fa' }}>insurance.</span>
                </h1>
                <p style={{ color: '#cbd5e1', fontSize: '17px', lineHeight: 1.7, margin: '0 0 28px', maxWidth: '520px' }}>
                  We compare rates from <strong style={{ color: '#fff' }}>15+ top carriers</strong> to find you the best 
                  coverage at the best price. Free, fast, and zero obligation — most quotes 
                  take less than 10 minutes.
                </p>

                <div style={{ display: 'flex', gap: '12px', flexWrap: 'wrap' as const }}>
                  <a href="#get-quote" style={{
                    display: 'inline-flex', alignItems: 'center', gap: '8px',
                    background: '#2563eb', color: '#fff', padding: '14px 28px', borderRadius: '8px',
                    fontSize: '16px', fontWeight: 700, textDecoration: 'none',
                    boxShadow: '0 4px 20px rgba(37,99,235,0.4)',
                    transition: 'transform 0.2s',
                  }}>
                    Get My Free Comparison <ArrowRight size={18} />
                  </a>
                  <a href={`tel:${PHONE_DIGITS}`} style={{
                    display: 'inline-flex', alignItems: 'center', gap: '8px',
                    background: 'rgba(255,255,255,0.08)', color: '#e2e8f0', padding: '14px 28px', borderRadius: '8px',
                    fontSize: '16px', fontWeight: 600, textDecoration: 'none',
                    border: '1px solid rgba(255,255,255,0.12)',
                  }}>
                    <Phone size={16} /> Call Us Now
                  </a>
                </div>

                {/* Trust badges */}
                <div style={{ display: 'flex', gap: '24px', marginTop: '32px', flexWrap: 'wrap' as const }}>
                  {[
                    { icon: <Shield size={16} />, text: 'Licensed & Insured' },
                    { icon: <Star size={16} />, text: '5-Star Google Reviews' },
                    { icon: <Clock size={16} />, text: 'Quotes in 10 Minutes' },
                  ].map((b, i) => (
                    <div key={i} style={{ display: 'flex', alignItems: 'center', gap: '6px', color: '#94a3b8', fontSize: '13px', fontWeight: 500 }}>
                      <span style={{ color: '#60a5fa' }}>{b.icon}</span> {b.text}
                    </div>
                  ))}
                </div>
              </div>

              {/* Right: Quick stats card */}
              <div style={{
                flex: '0 0 300px', background: 'rgba(255,255,255,0.04)', borderRadius: '16px',
                border: '1px solid rgba(255,255,255,0.08)', padding: '28px', backdropFilter: 'blur(10px)',
              }}>
                <p style={{ color: '#94a3b8', fontSize: '12px', fontWeight: 700, letterSpacing: '1.5px', textTransform: 'uppercase' as const, margin: '0 0 20px' }}>
                  WHY SWITCH TO US?
                </p>
                {[
                  { stat: '15+', label: 'Insurance Carriers', sub: 'We shop, you save' },
                  { stat: '$600+', label: 'Avg. Annual Savings', sub: 'For new customers' },
                  { stat: '10 min', label: 'Average Quote Time', sub: 'Fast & hassle-free' },
                  { stat: '1,500+', label: 'Happy Customers', sub: 'Across the Midwest' },
                ].map((s, i) => (
                  <div key={i} style={{ display: 'flex', gap: '14px', marginBottom: i < 3 ? '16px' : '0', alignItems: 'center' }}>
                    <div style={{
                      fontSize: '22px', fontWeight: 800, color: '#60a5fa', minWidth: '70px',
                      fontFamily: "'DM Sans', sans-serif",
                    }}>
                      {s.stat}
                    </div>
                    <div>
                      <div style={{ color: '#e2e8f0', fontSize: '14px', fontWeight: 600 }}>{s.label}</div>
                      <div style={{ color: '#64748b', fontSize: '12px' }}>{s.sub}</div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </section>

        {/* ═══ CARRIER LOGOS BANNER ═══ */}
        <section style={{ background: '#fff', borderBottom: '1px solid #e5e7eb', padding: '32px 24px' }}>
          <div style={{ maxWidth: '1100px', margin: '0 auto', textAlign: 'center' as const }}>
            <p style={{ color: '#94a3b8', fontSize: '13px', fontWeight: 600, letterSpacing: '1.5px', textTransform: 'uppercase' as const, margin: '0 0 24px' }}>
              We compare rates from these top-rated carriers
            </p>
            <div style={{
              display: 'flex', flexWrap: 'wrap' as const, justifyContent: 'center', alignItems: 'center', gap: '28px',
            }}>
              {CARRIERS.map((c, i) => (
                <img key={i} src={c.logo} alt={c.name} title={c.name} style={{
                  height: '32px', maxWidth: '100px', objectFit: 'contain' as const,
                  filter: 'grayscale(40%)', opacity: 0.7,
                  transition: 'all 0.3s',
                }}
                onMouseOver={(e) => { (e.target as HTMLImageElement).style.filter = 'grayscale(0%)'; (e.target as HTMLImageElement).style.opacity = '1'; }}
                onMouseOut={(e) => { (e.target as HTMLImageElement).style.filter = 'grayscale(40%)'; (e.target as HTMLImageElement).style.opacity = '0.7'; }}
                />
              ))}
            </div>
          </div>
        </section>

        {/* ═══ HOW IT WORKS ═══ */}
        <section style={{ background: '#fff', padding: '72px 24px' }}>
          <div style={{ maxWidth: '1000px', margin: '0 auto' }}>
            <div style={{ textAlign: 'center' as const, marginBottom: '48px' }}>
              <p style={{ color: '#2563eb', fontSize: '13px', fontWeight: 700, letterSpacing: '1.5px', textTransform: 'uppercase' as const, margin: '0 0 8px' }}>
                Simple Process
              </p>
              <h2 style={{ fontFamily: "'Playfair Display', serif", fontSize: '32px', fontWeight: 700, margin: '0', color: '#0f172a' }}>
                How It Works
              </h2>
            </div>

            <div style={{ display: 'flex', gap: '32px', flexWrap: 'wrap' as const, justifyContent: 'center' }}>
              {[
                { step: '1', icon: <Phone size={28} />, title: 'Tell Us About Your Policy', desc: 'Share your current declarations page or just give us a call. We handle everything from there.' },
                { step: '2', icon: <Users size={28} />, title: 'We Shop 15+ Carriers', desc: 'Our team compares rates across our carrier partners to find the best combination of price and coverage.' },
                { step: '3', icon: <DollarSign size={28} />, title: 'You Save Money', desc: 'Review your options and choose the best fit. Most customers save hundreds per year — and we make switching easy.' },
              ].map((s, i) => (
                <div key={i} style={{
                  flex: '1 1 280px', maxWidth: '320px', padding: '32px',
                  background: '#f8fafc', borderRadius: '16px', border: '1px solid #e5e7eb',
                  position: 'relative',
                }}>
                  <div style={{
                    position: 'absolute', top: '-14px', left: '32px',
                    background: '#2563eb', color: '#fff', width: '28px', height: '28px', borderRadius: '50%',
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                    fontSize: '13px', fontWeight: 800,
                  }}>
                    {s.step}
                  </div>
                  <div style={{ color: '#2563eb', marginBottom: '16px' }}>{s.icon}</div>
                  <h3 style={{ fontSize: '18px', fontWeight: 700, margin: '0 0 8px', color: '#0f172a' }}>{s.title}</h3>
                  <p style={{ fontSize: '14px', color: '#64748b', lineHeight: 1.7, margin: 0 }}>{s.desc}</p>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* ═══ WHY BETTER CHOICE ═══ */}
        <section style={{ background: '#f0f4f8', padding: '72px 24px' }}>
          <div style={{ maxWidth: '1000px', margin: '0 auto' }}>
            <div style={{ textAlign: 'center' as const, marginBottom: '48px' }}>
              <p style={{ color: '#2563eb', fontSize: '13px', fontWeight: 700, letterSpacing: '1.5px', textTransform: 'uppercase' as const, margin: '0 0 8px' }}>
                The Better Choice Difference
              </p>
              <h2 style={{ fontFamily: "'Playfair Display', serif", fontSize: '32px', fontWeight: 700, margin: '0 0 12px', color: '#0f172a' }}>
                Why Families Trust Us With Their Insurance
              </h2>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: '24px' }}>
              {[
                { icon: <Shield size={24} />, title: 'Independent Agency', desc: "We don't work for one carrier — we work for you. We shop the market to find the best coverage at the best price." },
                { icon: <DollarSign size={24} />, title: 'No Cost to You', desc: "Our service is completely free. We're paid by the carriers, so you get expert advice without any fees or markups." },
                { icon: <Clock size={24} />, title: 'Fast & Easy', desc: "Most quotes take just 10 minutes. We handle all the paperwork and make switching carriers seamless." },
                { icon: <Users size={24} />, title: 'Personal Service', desc: "You'll always talk to a real person who knows your name and your policies — not a call center." },
                { icon: <CheckCircle size={24} />, title: 'Claims Advocacy', desc: "When you need to file a claim, we go to bat for you. We advocate on your behalf and guide you through the process." },
                { icon: <Star size={24} />, title: 'Ongoing Reviews', desc: "We proactively review your policies at renewal to make sure you're always getting the best deal as rates change." },
              ].map((item, i) => (
                <div key={i} style={{
                  padding: '28px', background: '#fff', borderRadius: '12px',
                  border: '1px solid #e5e7eb', display: 'flex', gap: '16px',
                }}>
                  <div style={{
                    width: '44px', height: '44px', borderRadius: '10px', flexShrink: 0,
                    background: '#eff6ff', display: 'flex', alignItems: 'center', justifyContent: 'center',
                    color: '#2563eb',
                  }}>
                    {item.icon}
                  </div>
                  <div>
                    <h3 style={{ fontSize: '16px', fontWeight: 700, margin: '0 0 6px', color: '#0f172a' }}>{item.title}</h3>
                    <p style={{ fontSize: '14px', color: '#64748b', lineHeight: 1.6, margin: 0 }}>{item.desc}</p>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* ═══ TESTIMONIALS ═══ */}
        <section style={{ background: '#fff', padding: '72px 24px' }}>
          <div style={{ maxWidth: '1000px', margin: '0 auto' }}>
            <div style={{ textAlign: 'center' as const, marginBottom: '40px' }}>
              <p style={{ color: '#2563eb', fontSize: '13px', fontWeight: 700, letterSpacing: '1.5px', textTransform: 'uppercase' as const, margin: '0 0 8px' }}>
                Customer Stories
              </p>
              <h2 style={{ fontFamily: "'Playfair Display', serif", fontSize: '32px', fontWeight: 700, margin: '0', color: '#0f172a' }}>
                What Our Customers Say
              </h2>
            </div>
            <div style={{ display: 'flex', gap: '24px', flexWrap: 'wrap' as const, justifyContent: 'center' }}>
              {[
                { name: 'Maria T.', location: 'Chicago, IL', quote: "Better Choice saved us over $800 a year on our home and auto bundle. Same great coverage, way less money. I honestly couldn't believe the difference until I saw it side by side.", stars: 5 },
                { name: 'James K.', location: 'Naperville, IL', quote: "They shopped my renewal across a dozen carriers and found me a better rate in 15 minutes flat. Super easy process and Evan really took the time to explain every option.", stars: 5 },
                { name: 'Linda S.', location: 'Aurora, IL', quote: "After my old agent retired, I felt completely lost. Better Choice took over everything seamlessly and actually improved my coverage while lowering my monthly bill. Lifesavers.", stars: 5 },
              ].map((t, i) => (
                <div key={i} style={{
                  flex: '1 1 280px', maxWidth: '320px', padding: '28px',
                  background: '#f8fafc', borderRadius: '16px', border: '1px solid #e5e7eb',
                }}>
                  <div style={{ display: 'flex', gap: '2px', marginBottom: '14px' }}>
                    {Array.from({ length: t.stars }).map((_, j) => (
                      <Star key={j} size={16} fill="#f59e0b" color="#f59e0b" />
                    ))}
                  </div>
                  <p style={{ fontSize: '14px', color: '#334155', lineHeight: 1.7, margin: '0 0 16px', fontStyle: 'italic' }}>
                    "{t.quote}"
                  </p>
                  <div>
                    <p style={{ fontSize: '14px', fontWeight: 700, color: '#0f172a', margin: 0 }}>{t.name}</p>
                    <p style={{ fontSize: '12px', color: '#94a3b8', margin: 0 }}>{t.location}</p>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* ═══ CONTACT / QUOTE FORM ═══ */}
        <section id="get-quote" style={{
          background: 'linear-gradient(145deg, #0a1628 0%, #132042 40%, #1a3a5c 100%)',
          padding: '72px 24px', position: 'relative',
        }}>
          <div style={{
            position: 'absolute', inset: 0, opacity: 0.04,
            backgroundImage: 'linear-gradient(rgba(255,255,255,.1) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,.1) 1px, transparent 1px)',
            backgroundSize: '60px 60px',
          }} />
          <div style={{ maxWidth: '600px', margin: '0 auto', position: 'relative', zIndex: 1 }}>
            <div style={{ textAlign: 'center' as const, marginBottom: '36px' }}>
              <h2 style={{ fontFamily: "'Playfair Display', serif", fontSize: '32px', fontWeight: 700, margin: '0 0 12px', color: '#fff' }}>
                Get Your Free Comparison
              </h2>
              <p style={{ color: '#94a3b8', fontSize: '16px', margin: 0, lineHeight: 1.6 }}>
                Fill out the form below and we'll get back to you within one business day with your personalized quote comparison.
              </p>
            </div>

            {!submitted ? (
              <div style={{
                background: 'rgba(255,255,255,0.05)', borderRadius: '16px', padding: '32px',
                border: '1px solid rgba(255,255,255,0.08)', backdropFilter: 'blur(10px)',
              }}>
                {[
                  { label: 'Your Name', key: 'name', type: 'text', placeholder: 'John Smith', required: true },
                  { label: 'Phone Number', key: 'phone', type: 'tel', placeholder: '(555) 123-4567', required: true },
                  { label: 'Email (optional)', key: 'email', type: 'email', placeholder: 'john@example.com', required: false },
                ].map((field, i) => (
                  <div key={i} style={{ marginBottom: '16px' }}>
                    <label style={{ display: 'block', color: '#94a3b8', fontSize: '13px', fontWeight: 600, marginBottom: '6px' }}>
                      {field.label} {field.required && <span style={{ color: '#f87171' }}>*</span>}
                    </label>
                    <input
                      type={field.type}
                      placeholder={field.placeholder}
                      value={(formData as any)[field.key]}
                      onChange={(e) => setFormData(prev => ({ ...prev, [field.key]: e.target.value }))}
                      style={{
                        width: '100%', padding: '12px 16px', fontSize: '15px', borderRadius: '8px',
                        border: '1px solid rgba(255,255,255,0.12)', background: 'rgba(255,255,255,0.06)',
                        color: '#fff', outline: 'none', boxSizing: 'border-box' as const,
                      }}
                    />
                  </div>
                ))}
                <div style={{ marginBottom: '20px' }}>
                  <label style={{ display: 'block', color: '#94a3b8', fontSize: '13px', fontWeight: 600, marginBottom: '6px' }}>
                    Anything else we should know?
                  </label>
                  <textarea
                    rows={3}
                    placeholder="e.g. Looking to bundle home & auto, current premium is $X/month..."
                    value={formData.message}
                    onChange={(e) => setFormData(prev => ({ ...prev, message: e.target.value }))}
                    style={{
                      width: '100%', padding: '12px 16px', fontSize: '15px', borderRadius: '8px',
                      border: '1px solid rgba(255,255,255,0.12)', background: 'rgba(255,255,255,0.06)',
                      color: '#fff', outline: 'none', resize: 'vertical' as const, boxSizing: 'border-box' as const,
                      fontFamily: "'DM Sans', sans-serif",
                    }}
                  />
                </div>
                <button
                  onClick={handleSubmit}
                  disabled={submitting || !formData.name || !formData.phone}
                  style={{
                    width: '100%', padding: '16px', fontSize: '16px', fontWeight: 700,
                    background: (!formData.name || !formData.phone) ? '#475569' : '#2563eb',
                    color: '#fff', border: 'none', borderRadius: '8px', cursor: 'pointer',
                    boxShadow: '0 4px 20px rgba(37,99,235,0.3)',
                    opacity: submitting ? 0.7 : 1,
                  }}
                >
                  {submitting ? 'Submitting...' : 'Get My Free Quote Comparison →'}
                </button>
                <p style={{ textAlign: 'center' as const, color: '#64748b', fontSize: '12px', marginTop: '12px' }}>
                  No spam. No obligation. Just savings.
                </p>
              </div>
            ) : (
              <div style={{
                background: 'rgba(255,255,255,0.05)', borderRadius: '16px', padding: '48px 32px',
                border: '1px solid rgba(34,197,94,0.3)', textAlign: 'center' as const,
              }}>
                <CheckCircle size={48} color="#22c55e" style={{ marginBottom: '16px' }} />
                <h3 style={{ color: '#fff', fontSize: '22px', fontWeight: 700, margin: '0 0 8px' }}>
                  We got your request!
                </h3>
                <p style={{ color: '#94a3b8', fontSize: '16px', margin: '0 0 24px', lineHeight: 1.6 }}>
                  Our team will review your information and get back to you within one business day with your personalized quote comparison.
                </p>
                <p style={{ color: '#64748b', fontSize: '14px', margin: 0 }}>
                  Need faster help? Call us at{' '}
                  <a href={`tel:${PHONE_DIGITS}`} style={{ color: '#60a5fa', fontWeight: 700, textDecoration: 'none' }}>
                    {PHONE}
                  </a>
                </p>
              </div>
            )}

            {/* Or call us */}
            <div style={{ textAlign: 'center' as const, marginTop: '24px' }}>
              <p style={{ color: '#64748b', fontSize: '14px', margin: '0 0 8px' }}>Prefer to talk to a person?</p>
              <a href={`tel:${PHONE_DIGITS}`} style={{
                display: 'inline-flex', alignItems: 'center', gap: '8px',
                color: '#93c5fd', fontSize: '18px', fontWeight: 700, textDecoration: 'none',
              }}>
                <Phone size={18} /> {PHONE}
              </a>
            </div>
          </div>
        </section>

        {/* ═══ FOOTER ═══ */}
        <footer style={{ background: '#060d18', padding: '32px 24px', textAlign: 'center' as const }}>
          <img src="/carrier-logos/bci_header_white.png" alt="Better Choice Insurance" style={{ height: '28px', marginBottom: '12px', opacity: 0.6 }} />
          <p style={{ color: '#475569', fontSize: '13px', margin: '0 0 4px' }}>
            Better Choice Insurance Group | {PHONE} | {EMAIL}
          </p>
          <p style={{ color: '#334155', fontSize: '11px', margin: 0 }}>
            © {new Date().getFullYear()} Better Choice Insurance Group. All rights reserved.
          </p>
        </footer>
      </div>
    </>
  );
}
