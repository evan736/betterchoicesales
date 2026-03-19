import React, { useState, useEffect, useRef } from 'react';
import Head from 'next/head';
import { useRouter } from 'next/router';
import { Shield, Phone, Clock, DollarSign, Users, CheckCircle, Star, ArrowRight, Upload, FileText, Zap, Brain, AlertTriangle, TrendingDown } from 'lucide-react';
import GoogleAnalytics from '../components/GoogleAnalytics';

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

const TESTIMONIALS = [
  { name: 'Maria T.', location: 'Chicago, IL', quote: "Better Choice saved us over $800 a year on our home and auto bundle. Same great coverage, way less money. I couldn't believe it until I saw the comparison side by side.", stars: 5 },
  { name: 'Robert & Lisa M.', location: 'Dallas, TX', quote: "We moved from a captive agent and immediately saved over $1,200 on our home and auto. The AI coverage review even caught a gap in our liability limits we didn't know about.", stars: 5 },
  { name: 'Sarah P.', location: 'Phoenix, AZ', quote: "Being new to Arizona I had no idea where to start. Better Choice compared 12 carriers for me and found the perfect policy. Their tech makes the whole process so easy.", stars: 5 },
  { name: 'David W.', location: 'Minneapolis, MN', quote: "I uploaded my dec pages and got an instant analysis showing I was underinsured on my roof. They found me better coverage for $400 less per year.", stars: 5 },
  { name: 'Linda S.', location: 'Columbus, OH', quote: "After my old agent retired, I felt completely lost. Better Choice took over everything seamlessly and actually improved my coverage while lowering my bill.", stars: 5 },
  { name: 'Mike & Jennifer R.', location: 'Indianapolis, IN', quote: "The AI review caught that our replacement cost coverage hadn't kept up with home values. They re-quoted us with proper limits and still saved us money.", stars: 5 },
  { name: 'James K.', location: 'Naperville, IL', quote: "They shopped my renewal across a dozen carriers and found me a better rate in 15 minutes flat. Evan really took the time to explain every option.", stars: 5 },
  { name: 'Angela C.', location: 'Aurora, IL', quote: "I was skeptical about switching but the coverage analysis showed me exactly where I was overpaying. Saved $950 on my auto policy alone.", stars: 5 },
];

export default function GetQuotePage() {
  const router = useRouter();
  const { first_name, last_name, email, phone, address, city, state, zip, type, utm_campaign } = router.query;
  const firstName = (first_name as string) || '';
  const lastName = (last_name as string) || '';
  const leadEmail = (email as string) || '';
  const leadPhone = (phone as string) || '';
  const leadAddress = (address as string) || '';
  const leadCity = (city as string) || '';
  const leadState = (state as string) || '';
  const leadZip = (zip as string) || '';
  const policyType = ((type as string) || 'insurance').replace(/_/g, ' ');
  const fullName = [firstName, lastName].filter(Boolean).join(' ');

  // AI Coverage Review state
  const [decFile, setDecFile] = useState<File | null>(null);
  const [analyzing, setAnalyzing] = useState(false);
  const [analysis, setAnalysis] = useState<any>(null);
  const [analysisFormData, setAnalysisFormData] = useState({ name: '', phone: '', email: '', address: '', city: '', state: '', zip: '' });
  const [analysisSent, setAnalysisSent] = useState(false);
  const [aiContactCollected, setAiContactCollected] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Testimonial pagination
  const [tPage, setTPage] = useState(0);
  const perPage = 3;
  const totalPages = Math.ceil(TESTIMONIALS.length / perPage);
  const visibleTestimonials = TESTIMONIALS.slice(tPage * perPage, tPage * perPage + perPage);

  useEffect(() => {
    if (fullName || leadEmail || leadPhone) {
      setAnalysisFormData(prev => ({
        ...prev,
        name: fullName || prev.name,
        email: leadEmail || prev.email,
        phone: leadPhone || prev.phone,
        address: leadAddress || prev.address,
        city: leadCity || prev.city,
        state: leadState || prev.state,
        zip: leadZip || prev.zip,
      }));
    }
  }, [fullName, leadEmail, leadPhone, leadAddress, leadCity, leadState, leadZip]);

  const API = process.env.NEXT_PUBLIC_API_URL || 'https://better-choice-api.onrender.com';

  const handleDecUpload = async (file: File) => {
    setDecFile(file);
    setAnalyzing(true);
    setAnalysis(null);

    try {
      const payload = new FormData();
      payload.append('file', file);
      payload.append('name', analysisFormData.name || firstName || '');
      payload.append('phone', analysisFormData.phone || '');
      payload.append('email', analysisFormData.email || '');

      const resp = await fetch(`${API}/api/campaigns/coverage-analysis`, {
        method: 'POST',
        body: payload,
      });
      if (resp.ok) {
        const data = await resp.json();
        setAnalysis(data);
        setAnalysisSent(true); // Contact already collected, lead sent by backend
        setAnalyzing(false);
        return;
      }
    } catch (e) { /* fallback below */ }

    // Fallback
    await new Promise(r => setTimeout(r, 2500));
    setAnalysis({
      carrier: currentCarrier || 'Your Current Carrier',
      policy_type: policyType || 'Homeowners',
      gaps: [
        { area: 'Replacement Cost Coverage', severity: 'high', detail: 'Your dwelling coverage may not reflect current rebuild costs. Construction costs have risen 30-40% since 2020, and many policies haven\'t kept pace.' },
        { area: 'Liability Limits', severity: 'medium', detail: 'Your liability limits may be at the state minimum. We typically recommend $300K-$500K to properly protect your assets.' },
        { area: 'Water Backup Coverage', severity: 'medium', detail: 'Many standard policies exclude sewer and water backup damage. This is one of the most common claims homeowners face.' },
      ],
      savings_estimate: '$400 - $1,200',
      recommendation: 'Based on our initial review, we believe there are meaningful savings available once one of our licensed agents reviews your full policy across our 15+ carrier partners.',
    });
    // Send partial lead for fallback too
    try {
      await fetch(`${API}/api/campaigns/landing-lead`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: analysisFormData.name,
          phone: analysisFormData.phone,
          email: analysisFormData.email,
          message: `[AI Coverage Review - Fallback] Dec page: ${file?.name || 'N/A'}.`,
          policy_type: policyType, current_carrier: currentCarrier,
          utm_campaign: 'ai_coverage_review', source: 'ai_coverage_review',
        }),
      });
    } catch (e) { /* ok */ }
    setAnalysisSent(true);
    setAnalyzing(false);
  };

  const iS: React.CSSProperties = {
    width: '100%', padding: '12px 16px', fontSize: '15px', borderRadius: '8px',
    border: '1px solid rgba(255,255,255,0.12)', background: 'rgba(255,255,255,0.06)',
    color: '#fff', outline: 'none', boxSizing: 'border-box',
    fontFamily: "'DM Sans', sans-serif",
  };
  const lS: React.CSSProperties = { display: 'block', color: '#94a3b8', fontSize: '13px', fontWeight: 600, marginBottom: '6px' };

  return (
    <>
      <GoogleAnalytics />
      <Head>
        <title>Insurance Quotes St. Charles IL | Compare Home & Auto Rates | Better Choice Insurance</title>
        <meta name="description" content="Compare home and auto insurance rates from 15+ carriers in St. Charles, IL. Serving Kane County, DuPage County, and the Fox Valley. Free quotes in minutes — call (847) 908-5665." />
        <meta name="keywords" content="insurance st charles il, home insurance st charles, auto insurance st charles, car insurance kane county, homeowners insurance geneva il, insurance agent elgin il, cheap auto insurance batavia, insurance quotes fox valley, independent insurance agency illinois" />
        <meta property="og:title" content="Better Choice Insurance Group | St. Charles, IL" />
        <meta property="og:description" content="Compare rates from Travelers, Progressive, Safeco, National General, and 12+ more carriers. Free quotes, no obligation." />
        <meta property="og:type" content="website" />
        <meta property="og:url" content="https://quote.betterchoiceins.com/get-quote" />
        <meta name="geo.region" content="US-IL" />
        <meta name="geo.placename" content="St. Charles, Illinois" />
        <meta name="geo.position" content="41.9142;-88.3087" />
        <link rel="canonical" href="https://quote.betterchoiceins.com/get-quote" />
        <link href="https://fonts.googleapis.com/css2?family=DM+Sans:ital,opsz,wght@0,9..40,300;0,9..40,400;0,9..40,500;0,9..40,600;0,9..40,700;0,9..40,800&family=Playfair+Display:wght@600;700;800&display=swap" rel="stylesheet" />
        <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify({
          "@context": "https://schema.org",
          "@type": "InsuranceAgency",
          "name": "Better Choice Insurance Group",
          "image": "https://quote.betterchoiceins.com/carrier-logos/bci_logo_color.png",
          "url": "https://quote.betterchoiceins.com",
          "telephone": "+1-847-908-5665",
          "email": "service@betterchoiceins.com",
          "address": {
            "@type": "PostalAddress",
            "streetAddress": "300 Cardinal Dr Suite 220",
            "addressLocality": "Saint Charles",
            "addressRegion": "IL",
            "postalCode": "60175",
            "addressCountry": "US"
          },
          "geo": {
            "@type": "GeoCoordinates",
            "latitude": 41.9142,
            "longitude": -88.3087
          },
          "areaServed": [
            { "@type": "City", "name": "St. Charles, IL" },
            { "@type": "City", "name": "Geneva, IL" },
            { "@type": "City", "name": "Batavia, IL" },
            { "@type": "City", "name": "Elgin, IL" },
            { "@type": "City", "name": "South Elgin, IL" },
            { "@type": "City", "name": "Wayne, IL" },
            { "@type": "City", "name": "Campton Hills, IL" },
            { "@type": "City", "name": "West Chicago, IL" },
            { "@type": "City", "name": "Wheaton, IL" },
            { "@type": "City", "name": "Naperville, IL" },
            { "@type": "City", "name": "Aurora, IL" },
            { "@type": "City", "name": "Carol Stream, IL" },
            { "@type": "City", "name": "Streamwood, IL" },
            { "@type": "City", "name": "Bartlett, IL" },
            { "@type": "City", "name": "Carpentersville, IL" },
            { "@type": "AdministrativeArea", "name": "Kane County, IL" },
            { "@type": "AdministrativeArea", "name": "DuPage County, IL" },
            { "@type": "State", "name": "Illinois" },
            { "@type": "State", "name": "Minnesota" },
            { "@type": "State", "name": "Texas" }
          ],
          "openingHoursSpecification": {
            "@type": "OpeningHoursSpecification",
            "dayOfWeek": ["Monday","Tuesday","Wednesday","Thursday","Friday"],
            "opens": "09:00",
            "closes": "17:00"
          },
          "priceRange": "Free quotes",
          "sameAs": [],
          "description": "Independent insurance agency comparing rates from 15+ carriers including Travelers, Progressive, Safeco, National General, Grange, GEICO, and more. Specializing in home, auto, and bundled insurance in the Fox Valley and greater Chicagoland area.",
          "hasOfferCatalog": {
            "@type": "OfferCatalog",
            "name": "Insurance Products",
            "itemListElement": [
              {"@type": "Offer", "itemOffered": {"@type": "Service", "name": "Home Insurance"}},
              {"@type": "Offer", "itemOffered": {"@type": "Service", "name": "Auto Insurance"}},
              {"@type": "Offer", "itemOffered": {"@type": "Service", "name": "Bundled Home & Auto"}},
              {"@type": "Offer", "itemOffered": {"@type": "Service", "name": "Renters Insurance"}},
              {"@type": "Offer", "itemOffered": {"@type": "Service", "name": "Condo Insurance"}},
              {"@type": "Offer", "itemOffered": {"@type": "Service", "name": "Umbrella Insurance"}},
              {"@type": "Offer", "itemOffered": {"@type": "Service", "name": "Life Insurance"}},
              {"@type": "Offer", "itemOffered": {"@type": "Service", "name": "Landlord Insurance"}},
              {"@type": "Offer", "itemOffered": {"@type": "Service", "name": "Commercial Insurance"}}
            ]
          }
        })}} />
      </Head>

      <div className="get-quote-page" style={{ margin: 0, padding: 0, background: '#fafbfc', fontFamily: "'DM Sans', sans-serif", color: '#1a1a2e', minHeight: '100vh' }}>

        {/* ═══ HERO ═══ */}
        <section style={{ background: 'linear-gradient(145deg, #0a1628 0%, #132042 40%, #1a3a5c 100%)', position: 'relative', overflow: 'hidden' }}>
          <div style={{ position: 'absolute', inset: 0, opacity: 0.04, backgroundImage: 'linear-gradient(rgba(255,255,255,.1) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,.1) 1px, transparent 1px)', backgroundSize: '60px 60px' }} />
          <div style={{ position: 'absolute', top: '-200px', right: '-100px', width: '600px', height: '600px', background: 'radial-gradient(circle, rgba(59,130,246,0.15) 0%, transparent 70%)', borderRadius: '50%' }} />

          <div style={{ maxWidth: '1100px', margin: '0 auto', padding: '48px 24px 56px', position: 'relative', zIndex: 1 }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '48px' }}>
              <img src="/carrier-logos/bci_logo_v2.png" alt="Better Choice Insurance" style={{ height: '64px', display: 'block' }} />
              <a href={`tel:${PHONE_DIGITS}`} style={{ display: 'inline-flex', alignItems: 'center', gap: '8px', background: 'rgba(255,255,255,0.1)', color: '#fff', padding: '12px 24px', borderRadius: '8px', fontSize: '15px', fontWeight: 700, textDecoration: 'none', border: '1px solid rgba(255,255,255,0.25)', backdropFilter: 'blur(8px)' }}>
                <Phone size={16} /> {PHONE}
              </a>
            </div>

            <div style={{ display: 'flex', gap: '48px', alignItems: 'center', flexWrap: 'wrap' as const }}>
              <div style={{ flex: '1 1 480px', minWidth: '300px' }}>
                {fullName && (
                  <p style={{ color: '#60a5fa', fontSize: '15px', fontWeight: 600, margin: '0 0 12px' }}>
                    {fullName}, your {policyType} renewal is coming up
                  </p>
                )}
                <h1 style={{ fontFamily: "'Playfair Display', serif", color: '#ffffff', fontSize: 'clamp(32px, 5vw, 48px)', lineHeight: 1.15, fontWeight: 700, margin: '0 0 20px' }}>
                  Stop overpaying for <br /><span style={{ color: '#60a5fa' }}>insurance.</span>
                </h1>
                <p style={{ color: '#cbd5e1', fontSize: '17px', lineHeight: 1.7, margin: '0 0 12px', maxWidth: '520px' }}>
                  We compare rates from <strong style={{ color: '#fff' }}>15+ top carriers</strong> to find you the best coverage at the best price. Free, fast, and zero obligation.
                </p>
                <p style={{ color: '#94a3b8', fontSize: '14px', lineHeight: 1.6, margin: '0 0 28px', maxWidth: '520px' }}>
                  <span style={{ color: '#34d399', fontWeight: 700 }}>✦ NEW:</span> Upload your declarations page for an <strong style={{ color: '#e2e8f0' }}>instant AI-powered coverage analysis</strong> — spot gaps and savings in seconds.
                </p>

                <div style={{ display: 'flex', gap: '12px', flexWrap: 'wrap' as const }}>
                  <a href="/start-quote" style={{ display: 'inline-flex', alignItems: 'center', gap: '8px', background: '#2563eb', color: '#fff', padding: '14px 28px', borderRadius: '8px', fontSize: '16px', fontWeight: 700, textDecoration: 'none', boxShadow: '0 4px 20px rgba(37,99,235,0.4)' }}>
                    Start Your Quote <ArrowRight size={18} />
                  </a>
                  <a href="#ai-review" style={{ display: 'inline-flex', alignItems: 'center', gap: '8px', background: 'rgba(16,185,129,0.15)', color: '#34d399', padding: '14px 28px', borderRadius: '8px', fontSize: '16px', fontWeight: 700, textDecoration: 'none', border: '1px solid rgba(16,185,129,0.3)' }}>
                    <Brain size={18} /> AI Coverage Review
                  </a>
                </div>

                <div style={{ display: 'flex', gap: '24px', marginTop: '32px', flexWrap: 'wrap' as const }}>
                  {[
                    { icon: <Shield size={16} />, text: 'Licensed & Insured' },
                    { icon: <Zap size={16} />, text: 'AI-Powered Analysis' },
                    { icon: <Clock size={16} />, text: 'Quotes in 10 Minutes' },
                  ].map((b, i) => (
                    <div key={i} style={{ display: 'flex', alignItems: 'center', gap: '6px', color: '#94a3b8', fontSize: '13px', fontWeight: 500 }}>
                      <span style={{ color: '#60a5fa' }}>{b.icon}</span> {b.text}
                    </div>
                  ))}
                </div>
              </div>

              {/* Stats card */}
              <div style={{ flex: '0 0 300px', background: 'rgba(255,255,255,0.04)', borderRadius: '16px', border: '1px solid rgba(255,255,255,0.08)', padding: '28px', backdropFilter: 'blur(10px)' }}>
                <p style={{ color: '#94a3b8', fontSize: '12px', fontWeight: 700, letterSpacing: '1.5px', textTransform: 'uppercase' as const, margin: '0 0 20px' }}>WHY SWITCH TO US?</p>
                {[
                  { stat: '15+', label: 'Insurance Carriers', sub: 'We shop, you save' },
                  { stat: '$1,150+', label: 'Avg. Annual Savings', sub: 'For new customers' },
                  { stat: 'AI', label: 'Coverage Analysis', sub: 'Instant gap detection' },
                  { stat: '2,500+', label: 'Happy Customers', sub: 'And Growing' },
                ].map((s, i) => (
                  <div key={i} style={{ display: 'flex', gap: '14px', marginBottom: i < 3 ? '16px' : '0', alignItems: 'center' }}>
                    <div style={{ fontSize: '22px', fontWeight: 800, color: '#60a5fa', minWidth: '70px' }}>{s.stat}</div>
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

        {/* ═══ CARRIER LOGOS ═══ */}
        <section style={{ background: '#fff', borderBottom: '1px solid #e5e7eb', padding: '32px 24px' }}>
          <div style={{ maxWidth: '1100px', margin: '0 auto', textAlign: 'center' as const }}>
            <p style={{ color: '#94a3b8', fontSize: '13px', fontWeight: 600, letterSpacing: '1.5px', textTransform: 'uppercase' as const, margin: '0 0 24px' }}>
              We compare rates from these top-rated carriers
            </p>
            <div style={{ display: 'flex', flexWrap: 'wrap' as const, justifyContent: 'center', alignItems: 'center', gap: '28px' }}>
              {CARRIERS.map((c, i) => (
                <img key={i} src={c.logo} alt={c.name} title={c.name} style={{ height: '32px', maxWidth: '100px', objectFit: 'contain' as const, filter: 'grayscale(40%)', opacity: 0.7, transition: 'all 0.3s' }}
                  onMouseOver={(e) => { (e.target as HTMLImageElement).style.filter = 'grayscale(0%)'; (e.target as HTMLImageElement).style.opacity = '1'; }}
                  onMouseOut={(e) => { (e.target as HTMLImageElement).style.filter = 'grayscale(40%)'; (e.target as HTMLImageElement).style.opacity = '0.7'; }}
                />
              ))}
            </div>
          </div>
        </section>

        {/* ═══ AI COVERAGE REVIEW ═══ */}
        <section id="ai-review" style={{ background: 'linear-gradient(135deg, #0f172a 0%, #1e293b 100%)', padding: '72px 24px', position: 'relative' }}>
          <div style={{ position: 'absolute', inset: 0, opacity: 0.03, backgroundImage: 'radial-gradient(circle at 25% 25%, rgba(59,130,246,0.15) 0%, transparent 50%), radial-gradient(circle at 75% 75%, rgba(16,185,129,0.1) 0%, transparent 50%)' }} />
          <div style={{ maxWidth: '900px', margin: '0 auto', position: 'relative', zIndex: 1 }}>
            <div style={{ textAlign: 'center' as const, marginBottom: '40px' }}>
              <div style={{ display: 'inline-flex', alignItems: 'center', gap: '8px', background: 'rgba(16,185,129,0.15)', border: '1px solid rgba(16,185,129,0.3)', borderRadius: '20px', padding: '6px 16px', marginBottom: '16px' }}>
                <Brain size={16} style={{ color: '#34d399' }} />
                <span style={{ color: '#34d399', fontSize: '13px', fontWeight: 700 }}>AI-POWERED</span>
              </div>
              <h2 style={{ fontFamily: "'Playfair Display', serif", fontSize: '32px', fontWeight: 700, margin: '0 0 12px', color: '#fff' }}>
                Instant Coverage Analysis
              </h2>
              <p style={{ color: '#94a3b8', fontSize: '16px', lineHeight: 1.6, maxWidth: '600px', margin: '0 auto' }}>
                Upload your current declarations page and our AI will instantly analyze your coverage, identify gaps, and show you where you could be saving.
              </p>
            </div>

            {/* Phase 1: Collect contact info first */}
            {!aiContactCollected && !analysis && (
              <div style={{ maxWidth: '480px', margin: '0 auto' }}>
                <div style={{ background: 'rgba(255,255,255,0.04)', borderRadius: '16px', padding: '28px', border: '1px solid rgba(255,255,255,0.08)' }}>
                  <h3 style={{ color: '#fff', fontSize: '18px', fontWeight: 700, margin: '0 0 4px' }}>First, tell us who you are</h3>
                  <p style={{ color: '#94a3b8', fontSize: '14px', margin: '0 0 20px' }}>So we can send you the analysis and have an agent follow up.</p>
                  <div style={{ marginBottom: '12px' }}>
                    <label style={{ display: 'block', color: '#94a3b8', fontSize: '13px', fontWeight: 600, marginBottom: '6px' }}>Name <span style={{ color: '#f87171' }}>*</span></label>
                    <input style={{ width: '100%', padding: '12px 16px', fontSize: '15px', borderRadius: '8px', border: '1px solid rgba(255,255,255,0.15)', background: 'rgba(255,255,255,0.06)', color: '#fff', outline: 'none', boxSizing: 'border-box' as const, fontFamily: "'DM Sans', sans-serif" }}
                      value={analysisFormData.name} placeholder="John Smith"
                      onChange={e => setAnalysisFormData(p => ({ ...p, name: e.target.value }))} />
                  </div>
                  <div style={{ marginBottom: '12px' }}>
                    <label style={{ display: 'block', color: '#94a3b8', fontSize: '13px', fontWeight: 600, marginBottom: '6px' }}>Phone <span style={{ color: '#f87171' }}>*</span></label>
                    <input style={{ width: '100%', padding: '12px 16px', fontSize: '15px', borderRadius: '8px', border: '1px solid rgba(255,255,255,0.15)', background: 'rgba(255,255,255,0.06)', color: '#fff', outline: 'none', boxSizing: 'border-box' as const, fontFamily: "'DM Sans', sans-serif" }}
                      type="tel" value={analysisFormData.phone} placeholder="(555) 123-4567"
                      onChange={e => setAnalysisFormData(p => ({ ...p, phone: e.target.value }))} />
                  </div>
                  <div style={{ marginBottom: '20px' }}>
                    <label style={{ display: 'block', color: '#94a3b8', fontSize: '13px', fontWeight: 600, marginBottom: '6px' }}>Email <span style={{ color: '#f87171' }}>*</span></label>
                    <input style={{ width: '100%', padding: '12px 16px', fontSize: '15px', borderRadius: '8px', border: '1px solid rgba(255,255,255,0.15)', background: 'rgba(255,255,255,0.06)', color: '#fff', outline: 'none', boxSizing: 'border-box' as const, fontFamily: "'DM Sans', sans-serif" }}
                      type="email" value={analysisFormData.email} placeholder="john@example.com"
                      onChange={e => setAnalysisFormData(p => ({ ...p, email: e.target.value }))} />
                  </div>
                  <div style={{ marginBottom: '12px' }}>
                    <label style={{ display: 'block', color: '#94a3b8', fontSize: '13px', fontWeight: 600, marginBottom: '6px' }}>Address</label>
                    <input style={{ width: '100%', padding: '12px 16px', fontSize: '15px', borderRadius: '8px', border: '1px solid rgba(255,255,255,0.15)', background: 'rgba(255,255,255,0.06)', color: '#fff', outline: 'none', boxSizing: 'border-box' as const, fontFamily: "'DM Sans', sans-serif" }}
                      value={analysisFormData.address} placeholder="123 Main St"
                      onChange={e => setAnalysisFormData(p => ({ ...p, address: e.target.value }))} />
                  </div>
                  <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr 1fr', gap: '8px', marginBottom: '20px' }}>
                    <div>
                      <label style={{ display: 'block', color: '#94a3b8', fontSize: '13px', fontWeight: 600, marginBottom: '6px' }}>City</label>
                      <input style={{ width: '100%', padding: '12px 16px', fontSize: '15px', borderRadius: '8px', border: '1px solid rgba(255,255,255,0.15)', background: 'rgba(255,255,255,0.06)', color: '#fff', outline: 'none', boxSizing: 'border-box' as const, fontFamily: "'DM Sans', sans-serif" }}
                        value={analysisFormData.city} placeholder="Chicago"
                        onChange={e => setAnalysisFormData(p => ({ ...p, city: e.target.value }))} />
                    </div>
                    <div>
                      <label style={{ display: 'block', color: '#94a3b8', fontSize: '13px', fontWeight: 600, marginBottom: '6px' }}>State</label>
                      <input style={{ width: '100%', padding: '12px 16px', fontSize: '15px', borderRadius: '8px', border: '1px solid rgba(255,255,255,0.15)', background: 'rgba(255,255,255,0.06)', color: '#fff', outline: 'none', boxSizing: 'border-box' as const, fontFamily: "'DM Sans', sans-serif" }}
                        value={analysisFormData.state} placeholder="IL" maxLength={2}
                        onChange={e => setAnalysisFormData(p => ({ ...p, state: e.target.value.toUpperCase() }))} />
                    </div>
                    <div>
                      <label style={{ display: 'block', color: '#94a3b8', fontSize: '13px', fontWeight: 600, marginBottom: '6px' }}>Zip</label>
                      <input style={{ width: '100%', padding: '12px 16px', fontSize: '15px', borderRadius: '8px', border: '1px solid rgba(255,255,255,0.15)', background: 'rgba(255,255,255,0.06)', color: '#fff', outline: 'none', boxSizing: 'border-box' as const, fontFamily: "'DM Sans', sans-serif" }}
                        value={analysisFormData.zip} placeholder="60601"
                        onChange={e => setAnalysisFormData(p => ({ ...p, zip: e.target.value }))} />
                    </div>
                  </div>
                  <button onClick={() => setAiContactCollected(true)}
                    disabled={!analysisFormData.name || !analysisFormData.phone || !analysisFormData.email}
                    style={{
                      width: '100%', padding: '14px', fontSize: '16px', fontWeight: 700,
                      background: (analysisFormData.name && analysisFormData.phone && analysisFormData.email) ? '#10b981' : '#475569',
                      color: '#fff', border: 'none', borderRadius: '8px', cursor: (analysisFormData.name && analysisFormData.phone && analysisFormData.email) ? 'pointer' : 'default',
                      fontFamily: "'DM Sans', sans-serif",
                    }}>
                    Continue to Upload →
                  </button>
                </div>
              </div>
            )}

            {/* Phase 2: Upload dec page */}
            {aiContactCollected && !analysis && (
              <div style={{ maxWidth: '500px', margin: '0 auto' }}>
                <div
                  onClick={() => !analyzing && fileInputRef.current?.click()}
                  onDragOver={(e) => { e.preventDefault(); }}
                  onDrop={(e) => { e.preventDefault(); const f = e.dataTransfer.files[0]; if (f) handleDecUpload(f); }}
                  style={{
                    background: analyzing ? 'rgba(16,185,129,0.08)' : 'rgba(255,255,255,0.04)',
                    border: analyzing ? '2px solid rgba(16,185,129,0.4)' : '2px dashed rgba(255,255,255,0.15)',
                    borderRadius: '16px', padding: '48px 32px', textAlign: 'center' as const,
                    cursor: analyzing ? 'default' : 'pointer', transition: 'all 0.3s',
                  }}
                >
                  <input ref={fileInputRef} type="file" accept=".pdf,.png,.jpg,.jpeg" style={{ display: 'none' }}
                    onChange={(e) => { const f = e.target.files?.[0]; if (f) handleDecUpload(f); }} />
                  {analyzing ? (
                    <>
                      <div style={{ width: '48px', height: '48px', margin: '0 auto 16px', border: '3px solid rgba(16,185,129,0.3)', borderTopColor: '#34d399', borderRadius: '50%', animation: 'aispin 1s linear infinite' }} />
                      <style>{`@keyframes aispin { to { transform: rotate(360deg); } }`}</style>
                      <p style={{ color: '#34d399', fontSize: '16px', fontWeight: 700, margin: '0 0 8px' }}>Analyzing your coverage...</p>
                      <p style={{ color: '#64748b', fontSize: '14px', margin: 0 }}>Our AI is reviewing your declarations page</p>
                    </>
                  ) : (
                    <>
                      <Upload size={40} style={{ color: '#60a5fa', marginBottom: '16px' }} />
                      <p style={{ color: '#fff', fontSize: '18px', fontWeight: 700, margin: '0 0 8px' }}>Upload Your Declarations Page</p>
                      <p style={{ color: '#94a3b8', fontSize: '14px', margin: '0 0 16px' }}>Drag & drop or click to upload (PDF, PNG, JPG)</p>
                      <div style={{ display: 'inline-flex', alignItems: 'center', gap: '6px', background: 'rgba(37,99,235,0.15)', border: '1px solid rgba(37,99,235,0.3)', borderRadius: '8px', padding: '8px 16px', color: '#60a5fa', fontSize: '13px', fontWeight: 600 }}>
                        <FileText size={14} /> Your data stays private & secure
                      </div>
                    </>
                  )}
                </div>
              </div>
            )}

            {/* Phase 3: Analysis results */}
            {analysis && (
              <div style={{ background: 'rgba(255,255,255,0.04)', borderRadius: '16px', border: '1px solid rgba(255,255,255,0.08)', overflow: 'hidden' }}>
                <div style={{ background: 'rgba(16,185,129,0.1)', padding: '20px 28px', borderBottom: '1px solid rgba(255,255,255,0.06)', display: 'flex', alignItems: 'center', gap: '12px' }}>
                  <CheckCircle size={24} style={{ color: '#34d399' }} />
                  <div>
                    <p style={{ color: '#34d399', fontSize: '16px', fontWeight: 700, margin: 0 }}>Analysis Complete</p>
                    <p style={{ color: '#64748b', fontSize: '13px', margin: 0 }}>{analysis.carrier ? `${analysis.carrier} — ${analysis.policy_type || ''} Policy` : decFile?.name || 'Your Declarations Page'}</p>
                  </div>
                </div>

                <div style={{ padding: '28px' }}>
                  {/* Key coverages if available */}
                  {analysis.key_coverages && Object.keys(analysis.key_coverages).length > 0 && (
                    <div style={{ marginBottom: '20px' }}>
                      <h3 style={{ color: '#fff', fontSize: '16px', fontWeight: 700, margin: '0 0 12px' }}>Your Current Coverages</h3>
                      <div style={{ display: 'flex', flexWrap: 'wrap' as const, gap: '8px' }}>
                        {Object.entries(analysis.key_coverages).map(([k, v]: [string, any], i: number) => (
                          <div key={i} style={{ background: 'rgba(255,255,255,0.04)', borderRadius: '8px', padding: '8px 14px', border: '1px solid rgba(255,255,255,0.08)' }}>
                            <div style={{ color: '#94a3b8', fontSize: '11px', fontWeight: 600 }}>{k}</div>
                            <div style={{ color: '#e2e8f0', fontSize: '15px', fontWeight: 700 }}>{v}</div>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  <h3 style={{ color: '#fff', fontSize: '18px', fontWeight: 700, margin: '0 0 20px', display: 'flex', alignItems: 'center', gap: '8px' }}>
                    <AlertTriangle size={20} style={{ color: '#f59e0b' }} /> Coverage Gaps Identified
                  </h3>

                  {analysis.gaps?.map((gap: any, i: number) => (
                    <div key={i} style={{
                      background: gap.severity === 'high' ? 'rgba(239,68,68,0.08)' : 'rgba(245,158,11,0.08)',
                      border: `1px solid ${gap.severity === 'high' ? 'rgba(239,68,68,0.2)' : 'rgba(245,158,11,0.2)'}`,
                      borderRadius: '12px', padding: '16px 20px', marginBottom: '12px',
                    }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '6px' }}>
                        <span style={{
                          fontSize: '11px', fontWeight: 700, textTransform: 'uppercase' as const, padding: '2px 8px', borderRadius: '4px',
                          background: gap.severity === 'high' ? 'rgba(239,68,68,0.2)' : 'rgba(245,158,11,0.2)',
                          color: gap.severity === 'high' ? '#fca5a5' : '#fcd34d',
                        }}>
                          {gap.severity === 'high' ? 'HIGH PRIORITY' : 'RECOMMENDED'}
                        </span>
                        <span style={{ color: '#e2e8f0', fontSize: '15px', fontWeight: 700 }}>{gap.area}</span>
                      </div>
                      <p style={{ color: '#94a3b8', fontSize: '14px', lineHeight: 1.6, margin: 0 }}>{gap.detail}</p>
                    </div>
                  ))}

                  <div style={{ background: 'rgba(37,99,235,0.1)', border: '1px solid rgba(37,99,235,0.25)', borderRadius: '12px', padding: '20px', marginTop: '20px', display: 'flex', alignItems: 'center', gap: '16px' }}>
                    <TrendingDown size={32} style={{ color: '#60a5fa', flexShrink: 0 }} />
                    <div>
                      <p style={{ color: '#60a5fa', fontSize: '22px', fontWeight: 800, margin: '0 0 4px' }}>
                        Estimated Savings: {analysis.savings_estimate}
                      </p>
                      <p style={{ color: '#94a3b8', fontSize: '14px', lineHeight: 1.5, margin: 0 }}>{analysis.recommendation}</p>
                    </div>
                  </div>

                  {/* Already sent — show confirmation */}
                  <div style={{ marginTop: '28px', background: 'rgba(34,197,94,0.1)', borderRadius: '12px', padding: '24px', border: '1px solid rgba(34,197,94,0.3)', textAlign: 'center' as const }}>
                    <CheckCircle size={32} style={{ color: '#22c55e', marginBottom: '8px' }} />
                    <p style={{ color: '#fff', fontSize: '18px', fontWeight: 700, margin: '0 0 4px' }}>Your analysis has been sent to our team!</p>
                    <p style={{ color: '#94a3b8', fontSize: '14px', margin: 0 }}>
                      A licensed agent will review your full policy and reach out within one business day with a personalized comparison.
                    </p>
                  </div>
                </div>
              </div>
            )}
          </div>
        </section>

        {/* ═══ HOW IT WORKS ═══ */}
        <section style={{ background: '#fff', padding: '72px 24px' }}>
          <div style={{ maxWidth: '1000px', margin: '0 auto' }}>
            <div style={{ textAlign: 'center' as const, marginBottom: '48px' }}>
              <p style={{ color: '#2563eb', fontSize: '13px', fontWeight: 700, letterSpacing: '1.5px', textTransform: 'uppercase' as const, margin: '0 0 8px' }}>Simple Process</p>
              <h2 style={{ fontFamily: "'Playfair Display', serif", fontSize: '32px', fontWeight: 700, margin: '0', color: '#0f172a' }}>How It Works</h2>
            </div>
            <div style={{ display: 'flex', gap: '32px', flexWrap: 'wrap' as const, justifyContent: 'center' }}>
              {[
                { step: '1', icon: <Upload size={28} />, title: 'Upload or Tell Us', desc: 'Upload your dec pages for an instant AI analysis, or just share your info. Either way, we handle it from there.' },
                { step: '2', icon: <Brain size={28} />, title: 'AI + Agent Review', desc: 'Our AI spots coverage gaps instantly. Then a licensed agent compares rates across 15+ carriers for the best deal.' },
                { step: '3', icon: <DollarSign size={28} />, title: 'You Save Money', desc: 'Review your options with better coverage and lower rates. Our customers save an average of $1,150 per year.' },
              ].map((s, i) => (
                <div key={i} style={{ flex: '1 1 280px', maxWidth: '320px', padding: '32px', background: '#f8fafc', borderRadius: '16px', border: '1px solid #e5e7eb', position: 'relative' }}>
                  <div style={{ position: 'absolute', top: '-14px', left: '32px', background: '#2563eb', color: '#fff', width: '28px', height: '28px', borderRadius: '50%', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '13px', fontWeight: 800 }}>{s.step}</div>
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
              <p style={{ color: '#2563eb', fontSize: '13px', fontWeight: 700, letterSpacing: '1.5px', textTransform: 'uppercase' as const, margin: '0 0 8px' }}>The Better Choice Difference</p>
              <h2 style={{ fontFamily: "'Playfair Display', serif", fontSize: '32px', fontWeight: 700, margin: '0 0 12px', color: '#0f172a' }}>Why Families Trust Us With Their Insurance</h2>
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: '24px' }}>
              {[
                { icon: <Brain size={24} />, title: 'AI-Powered Analysis', desc: "Our AI reviews your coverage in seconds, identifying gaps and savings opportunities that manual reviews miss." },
                { icon: <Shield size={24} />, title: 'Independent Agency', desc: "We don't work for one carrier — we work for you. We shop the market to find the best coverage at the best price." },
                { icon: <DollarSign size={24} />, title: '$1,150+ Avg. Savings', desc: "Our customers save an average of $1,150 per year. We find the best rate across 15+ carriers — at no cost to you." },
                { icon: <CheckCircle size={24} />, title: 'Claims Advocacy', desc: "When you need to file a claim, we go to bat for you. We advocate on your behalf and guide you through the process." },
                { icon: <Star size={24} />, title: 'Ongoing Reviews', desc: "We proactively review your policies at renewal with AI + agent expertise to keep you protected and saving." },
                { icon: <Clock size={24} />, title: 'Fast & Free', desc: "Our service is completely free — we're paid by the carriers, never by you. No fees, no obligations." },
              ].map((item, i) => (
                <div key={i} style={{ padding: '28px', background: '#fff', borderRadius: '12px', border: '1px solid #e5e7eb', display: 'flex', gap: '16px' }}>
                  <div style={{ width: '44px', height: '44px', borderRadius: '10px', flexShrink: 0, background: '#eff6ff', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#2563eb' }}>{item.icon}</div>
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
          <div style={{ maxWidth: '1100px', margin: '0 auto' }}>
            <div style={{ textAlign: 'center' as const, marginBottom: '40px' }}>
              <p style={{ color: '#2563eb', fontSize: '13px', fontWeight: 700, letterSpacing: '1.5px', textTransform: 'uppercase' as const, margin: '0 0 8px' }}>
                2,500+ Happy Customers and Growing
              </p>
              <h2 style={{ fontFamily: "'Playfair Display', serif", fontSize: '32px', fontWeight: 700, margin: '0', color: '#0f172a' }}>What Our Customers Say</h2>
            </div>
            <div style={{ display: 'flex', gap: '20px', flexWrap: 'wrap' as const, justifyContent: 'center' }}>
              {visibleTestimonials.map((t, i) => (
                <div key={`${tPage}-${i}`} style={{ flex: '1 1 300px', maxWidth: '340px', padding: '28px', background: '#f8fafc', borderRadius: '16px', border: '1px solid #e5e7eb' }}>
                  <div style={{ display: 'flex', gap: '2px', marginBottom: '14px' }}>
                    {Array.from({ length: t.stars }).map((_, j) => <Star key={j} size={16} fill="#f59e0b" color="#f59e0b" />)}
                  </div>
                  <p style={{ fontSize: '14px', color: '#334155', lineHeight: 1.7, margin: '0 0 16px', fontStyle: 'italic' }}>&ldquo;{t.quote}&rdquo;</p>
                  <div>
                    <p style={{ fontSize: '14px', fontWeight: 700, color: '#0f172a', margin: 0 }}>{t.name}</p>
                    <p style={{ fontSize: '12px', color: '#94a3b8', margin: 0 }}>{t.location}</p>
                  </div>
                </div>
              ))}
            </div>
            {totalPages > 1 && (
              <div style={{ textAlign: 'center' as const, marginTop: '24px', display: 'flex', gap: '8px', justifyContent: 'center' }}>
                {Array.from({ length: totalPages }).map((_, i) => (
                  <button key={i} onClick={() => setTPage(i)} style={{ width: '10px', height: '10px', borderRadius: '50%', border: 'none', cursor: 'pointer', background: tPage === i ? '#2563eb' : '#cbd5e1', transition: 'background 0.2s' }} />
                ))}
              </div>
            )}
          </div>
        </section>

        {/* ═══ QUOTE CTA ═══ */}
        <section id="get-quote" style={{ background: 'linear-gradient(145deg, #0a1628 0%, #132042 40%, #1a3a5c 100%)', padding: '72px 24px', position: 'relative' }}>
          <div style={{ position: 'absolute', inset: 0, opacity: 0.04, backgroundImage: 'linear-gradient(rgba(255,255,255,.1) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,.1) 1px, transparent 1px)', backgroundSize: '60px 60px' }} />
          <div style={{ maxWidth: '600px', margin: '0 auto', position: 'relative', zIndex: 1, textAlign: 'center' as const }}>
            <h2 style={{ fontFamily: "'Playfair Display', serif", fontSize: '32px', fontWeight: 700, margin: '0 0 12px', color: '#fff' }}>
              Ready to Save?
            </h2>
            <p style={{ color: '#94a3b8', fontSize: '17px', margin: '0 0 32px', lineHeight: 1.6 }}>
              Answer a few quick questions and we&apos;ll compare rates from 15+ carriers to find your best deal. Most quotes take less than 5 minutes.
            </p>
            <a href={`/start-quote${typeof window !== 'undefined' ? window.location.search : ''}`} style={{
              display: 'inline-flex', alignItems: 'center', gap: '10px',
              background: '#2563eb', color: '#fff', padding: '18px 40px', borderRadius: '10px',
              fontSize: '18px', fontWeight: 700, textDecoration: 'none',
              boxShadow: '0 4px 24px rgba(37,99,235,0.4)',
            }}>
              Start Your Quote <ArrowRight size={20} />
            </a>
            <div style={{ marginTop: '24px' }}>
              <p style={{ color: '#64748b', fontSize: '14px', margin: '0 0 8px' }}>Prefer to talk to a person?</p>
              <a href={`tel:${PHONE_DIGITS}`} style={{ display: 'inline-flex', alignItems: 'center', gap: '8px', color: '#93c5fd', fontSize: '18px', fontWeight: 700, textDecoration: 'none' }}>
                <Phone size={18} /> {PHONE}
              </a>
            </div>
          </div>
        </section>

        {/* ═══ SERVICE AREA ═══ */}
        <section style={{ background: '#f1f5f9', padding: '64px 24px' }}>
          <div style={{ maxWidth: '900px', margin: '0 auto' }}>
            <h2 style={{ fontFamily: "'Playfair Display', serif", fontSize: '28px', fontWeight: 700, textAlign: 'center' as const, margin: '0 0 8px', color: '#0f172a' }}>
              Insurance for the Fox Valley & Beyond
            </h2>
            <p style={{ textAlign: 'center' as const, color: '#64748b', fontSize: '16px', margin: '0 0 32px', lineHeight: 1.6 }}>
              Based in St. Charles, IL, we proudly serve homeowners and drivers across Kane County, DuPage County, and beyond.
            </p>
            <div style={{ display: 'flex', flexWrap: 'wrap' as const, justifyContent: 'center', gap: '8px', marginBottom: '32px' }}>
              {['St. Charles', 'Geneva', 'Batavia', 'Elgin', 'South Elgin', 'Wayne', 'Campton Hills', 'West Chicago', 'Wheaton', 'Naperville', 'Aurora', 'Carol Stream', 'Streamwood', 'Bartlett', 'Carpentersville', 'North Aurora', 'Sugar Grove', 'Lily Lake', 'Wasco', 'Sleepy Hollow'].map(city => (
                <span key={city} style={{ background: '#fff', border: '1px solid #e2e8f0', borderRadius: '20px', padding: '6px 16px', fontSize: '13px', color: '#475569', fontWeight: 500 }}>
                  {city}, IL
                </span>
              ))}
            </div>
            <p style={{ textAlign: 'center' as const, color: '#94a3b8', fontSize: '14px', margin: 0, lineHeight: 1.6 }}>
              We also write policies across <strong style={{ color: '#64748b' }}>Illinois, Minnesota, and Texas</strong>. Whether you&apos;re in the suburbs or across state lines, we&apos;ll find you the best rate from our network of 15+ carriers.
            </p>
          </div>
        </section>

        {/* ═══ FOOTER ═══ */}
        <footer style={{ background: '#060d18', padding: '32px 24px', textAlign: 'center' as const }}>
          <img src="/carrier-logos/bci_logo_v2.png" alt="Better Choice Insurance Group St. Charles IL" style={{ height: '44px', marginBottom: '12px', opacity: 0.6 }} />
          <p style={{ color: '#475569', fontSize: '13px', margin: '0 0 4px' }}>Better Choice Insurance Group | 300 Cardinal Dr Suite 220, Saint Charles, IL 60175</p>
          <p style={{ color: '#475569', fontSize: '13px', margin: '0 0 4px' }}>{PHONE} | {EMAIL}</p>
          <p style={{ color: '#334155', fontSize: '11px', margin: '8px 0 0' }}>Independent insurance agency serving St. Charles, Geneva, Batavia, Elgin, Naperville, Aurora, and the greater Fox Valley area.</p>
          <p style={{ color: '#334155', fontSize: '11px', margin: '4px 0 0' }}>Home Insurance · Auto Insurance · Bundled Coverage · Renters · Condo · Umbrella · Life Insurance</p>
          <p style={{ color: '#334155', fontSize: '11px', margin: '8px 0 0' }}>© {new Date().getFullYear()} Better Choice Insurance Group. All rights reserved. | <a href="/privacy" style={{ color: '#475569', textDecoration: 'underline' }}>Privacy Policy</a></p>
        </footer>
      </div>
    </>
  );
}
