import React from 'react';
import Head from 'next/head';
import { useRouter } from 'next/router';
import { CheckCircle, Phone, Clock, Shield, Users } from 'lucide-react';

export default function QuoteConfirmation() {
  const router = useRouter();
  const { name, products } = router.query;
  const firstName = (name as string) || '';
  const productList = ((products as string) || '').split(',').filter(Boolean);

  return (
    <>
      <Head>
        <title>Quote Request Received | Better Choice Insurance</title>
        <link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700;800&family=Playfair+Display:wght@600;700;800&display=swap" rel="stylesheet" />
      </Head>
      <div className="get-quote-page" style={{ margin: 0, padding: 0, background: '#fafbfc', fontFamily: "'DM Sans', sans-serif", color: '#1a1a2e', minHeight: '100vh' }}>

        {/* Hero */}
        <section style={{ background: 'linear-gradient(145deg, #0a1628 0%, #132042 40%, #1a3a5c 100%)', position: 'relative', overflow: 'hidden' }}>
          <div style={{ position: 'absolute', inset: 0, opacity: 0.04, backgroundImage: 'linear-gradient(rgba(255,255,255,.1) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,.1) 1px, transparent 1px)', backgroundSize: '60px 60px' }} />
          <div style={{ maxWidth: '700px', margin: '0 auto', padding: '60px 24px 72px', position: 'relative', zIndex: 1, textAlign: 'center' as const }}>
            <img src="/carrier-logos/bci_logo_white.png" alt="Better Choice Insurance" style={{ height: '56px', marginBottom: '40px' }} />

            <div style={{ width: '72px', height: '72px', borderRadius: '50%', background: 'rgba(34,197,94,0.15)', border: '2px solid rgba(34,197,94,0.4)', display: 'flex', alignItems: 'center', justifyContent: 'center', margin: '0 auto 24px' }}>
              <CheckCircle size={36} color="#22c55e" />
            </div>

            <h1 style={{ fontFamily: "'Playfair Display', serif", color: '#fff', fontSize: '36px', fontWeight: 700, margin: '0 0 12px' }}>
              {firstName ? `Thanks, ${firstName}!` : 'Quote Request Received!'}
            </h1>
            <p style={{ color: '#cbd5e1', fontSize: '18px', lineHeight: 1.7, margin: '0 0 8px', maxWidth: '500px', marginLeft: 'auto', marginRight: 'auto' }}>
              Your quote request is in. A licensed agent will personally review your information and reach out within <strong style={{ color: '#fff' }}>one business day</strong>.
            </p>
          </div>
        </section>

        {/* What happens next */}
        <section style={{ background: '#fff', padding: '56px 24px' }}>
          <div style={{ maxWidth: '700px', margin: '0 auto' }}>
            <h2 style={{ fontFamily: "'Playfair Display', serif", fontSize: '26px', fontWeight: 700, margin: '0 0 32px', color: '#0f172a', textAlign: 'center' as const }}>
              Here&apos;s What Happens Next
            </h2>

            <div style={{ display: 'flex', flexDirection: 'column' as const, gap: '20px' }}>
              {[
                { num: '1', icon: <Shield size={24} />, title: 'We Review Your Info', desc: 'A licensed agent reviews your details and identifies the best carrier matches for your specific situation.' },
                { num: '2', icon: <Users size={24} />, title: 'We Shop 15+ Carriers', desc: 'We compare rates across our full carrier network to find you the best combination of coverage and price.' },
                { num: '3', icon: <Phone size={24} />, title: 'We Reach Out With Options', desc: 'Your agent will call or email you with a personalized comparison — typically within one business day.' },
              ].map((s, i) => (
                <div key={i} style={{ display: 'flex', gap: '16px', alignItems: 'flex-start', padding: '20px', background: '#f8fafc', borderRadius: '12px', border: '1px solid #e5e7eb' }}>
                  <div style={{ width: '44px', height: '44px', borderRadius: '10px', flexShrink: 0, background: '#eff6ff', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#2563eb' }}>
                    {s.icon}
                  </div>
                  <div>
                    <h3 style={{ fontSize: '16px', fontWeight: 700, margin: '0 0 4px', color: '#0f172a' }}>{s.title}</h3>
                    <p style={{ fontSize: '14px', color: '#64748b', lineHeight: 1.6, margin: 0 }}>{s.desc}</p>
                  </div>
                </div>
              ))}
            </div>

            {/* CTA */}
            <div style={{ textAlign: 'center' as const, marginTop: '40px', padding: '28px', background: '#f0f4f8', borderRadius: '16px' }}>
              <p style={{ color: '#475569', fontSize: '16px', margin: '0 0 12px' }}>Need faster help? Call us directly:</p>
              <a href="tel:8479085665" style={{ display: 'inline-flex', alignItems: 'center', gap: '8px', color: '#2563eb', fontSize: '24px', fontWeight: 800, textDecoration: 'none' }}>
                <Phone size={22} /> (847) 908-5665
              </a>
              <p style={{ color: '#94a3b8', fontSize: '13px', marginTop: '8px' }}>
                <Clock size={13} style={{ verticalAlign: 'middle', marginRight: '4px' }} />
                Mon–Fri 9am–6pm CST
              </p>
            </div>
          </div>
        </section>

        {/* Footer */}
        <footer style={{ background: '#060d18', padding: '32px 24px', textAlign: 'center' as const }}>
          <img src="/carrier-logos/bci_logo_white.png" alt="Better Choice Insurance" style={{ height: '36px', marginBottom: '12px', opacity: 0.6 }} />
          <p style={{ color: '#475569', fontSize: '13px', margin: '0 0 4px' }}>
            Better Choice Insurance Group | (847) 908-5665 | service@betterchoiceins.com
          </p>
          <p style={{ color: '#334155', fontSize: '11px', margin: 0 }}>
            © {new Date().getFullYear()} Better Choice Insurance Group. All rights reserved.
          </p>
        </footer>
      </div>
    </>
  );
}
