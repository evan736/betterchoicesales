import React from 'react';
import Head from 'next/head';
import { useRouter } from 'next/router';
import { Phone } from 'lucide-react';
import dynamic from 'next/dynamic';
import GoogleAnalytics from '../components/GoogleAnalytics';
const QuoteIntakeForm = dynamic(() => import('../components/QuoteIntakeForm'), { ssr: false });

export default function StartQuotePage() {
  const router = useRouter();
  const { name, type, carrier, xdate, utm_campaign } = router.query;
  const firstName = (name as string) || '';
  const policyType = ((type as string) || 'insurance').replace(/_/g, ' ');
  const currentCarrier = (carrier as string) || '';
  const renewalDate = (xdate as string) || '';

  return (
    <>
      <GoogleAnalytics />
      <Head>
        <title>Start Your Quote | Better Choice Insurance</title>
        <meta name="description" content="Get a personalized insurance quote. Compare rates from 15+ carriers in minutes." />
        <link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700;800&family=Playfair+Display:wght@600;700;800&display=swap" rel="stylesheet" />
      </Head>

      <div className="get-quote-page" style={{ margin: 0, padding: 0, minHeight: '100vh', fontFamily: "'DM Sans', sans-serif", color: '#1a1a2e',
        background: 'linear-gradient(145deg, #0a1628 0%, #132042 40%, #1a3a5c 100%)',
      }}>
        {/* Grid overlay */}
        <div style={{ position: 'fixed', inset: 0, opacity: 0.04, pointerEvents: 'none',
          backgroundImage: 'linear-gradient(rgba(255,255,255,.1) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,.1) 1px, transparent 1px)',
          backgroundSize: '60px 60px',
        }} />

        <div style={{ position: 'relative', zIndex: 1 }}>
          {/* Header */}
          <div style={{ maxWidth: '700px', margin: '0 auto', padding: '40px 24px 0', textAlign: 'center' as const }}>
            <a href="/get-quote">
              <img src="/carrier-logos/bci_logo_white.png" alt="Better Choice Insurance" style={{ height: '52px', marginBottom: '32px' }} />
            </a>
            <h1 style={{ fontFamily: "'Playfair Display', serif", color: '#fff', fontSize: '32px', fontWeight: 700, margin: '0 0 8px' }}>
              Start Your Quote
            </h1>
            <p style={{ color: '#94a3b8', fontSize: '16px', margin: '0 0 36px', lineHeight: 1.6 }}>
              Answer a few quick questions and we&apos;ll compare rates from 15+ carriers to find your best deal.
            </p>
          </div>

          {/* Form card */}
          <div style={{ maxWidth: '650px', margin: '0 auto', padding: '0 24px 40px' }}>
            <div style={{ background: 'rgba(255,255,255,0.05)', borderRadius: '16px', padding: '32px', border: '1px solid rgba(255,255,255,0.08)', backdropFilter: 'blur(10px)' }}>
              <QuoteIntakeForm
                initialName={firstName}
                policyType={policyType}
                currentCarrier={currentCarrier}
                renewalDate={renewalDate}
                utmCampaign={utm_campaign as string}
              />
            </div>

            <div style={{ textAlign: 'center' as const, marginTop: '24px' }}>
              <p style={{ color: '#64748b', fontSize: '14px', margin: '0 0 8px' }}>Prefer to talk to a person?</p>
              <a href="tel:8479085665" style={{ display: 'inline-flex', alignItems: 'center', gap: '8px', color: '#93c5fd', fontSize: '18px', fontWeight: 700, textDecoration: 'none' }}>
                <Phone size={18} /> (847) 908-5665
              </a>
            </div>
          </div>

          {/* Footer */}
          <footer style={{ padding: '24px', textAlign: 'center' as const, borderTop: '1px solid rgba(255,255,255,0.06)' }}>
            <p style={{ color: '#475569', fontSize: '12px', margin: 0 }}>
              © {new Date().getFullYear()} Better Choice Insurance Group. All rights reserved. | <a href="/privacy" style={{ color: '#64748b', textDecoration: 'underline' }}>Privacy Policy</a>
            </p>
          </footer>
        </div>
      </div>
    </>
  );
}
