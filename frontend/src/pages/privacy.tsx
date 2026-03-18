import React from 'react';
import Head from 'next/head';
import GoogleAnalytics from '../components/GoogleAnalytics';

export default function PrivacyPage() {
  return (
    <>
      <GoogleAnalytics />
      <Head>
        <title>Privacy Policy | Better Choice Insurance Group</title>
        <link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&display=swap" rel="stylesheet" />
      </Head>
      <div className="get-quote-page" style={{ background: '#fafbfc', minHeight: '100vh', fontFamily: "'DM Sans', sans-serif", color: '#1a1a2e' }}>
        <div style={{ background: 'linear-gradient(145deg, #0a1628, #132042)', padding: '48px 24px' }}>
          <div style={{ maxWidth: '800px', margin: '0 auto' }}>
            <img src="/carrier-logos/bci_logo_white.png" alt="BCI" style={{ height: '48px', marginBottom: '24px' }} />
            <h1 style={{ color: '#fff', fontSize: '32px', fontWeight: 700, margin: 0 }}>Privacy Policy</h1>
            <p style={{ color: '#94a3b8', fontSize: '14px', marginTop: '8px' }}>Last updated: February 27, 2026</p>
          </div>
        </div>

        <div style={{ maxWidth: '800px', margin: '0 auto', padding: '48px 24px', fontSize: '15px', color: '#334155', lineHeight: 1.8 }}>
          <h2 style={{ color: '#0f172a', fontSize: '22px', fontWeight: 700, margin: '0 0 12px' }}>Information We Collect</h2>
          <p>When you use our quote request forms, AI coverage review tool, or contact us, we collect personal information you provide, including your name, phone number, email address, mailing address, date of birth, information about drivers in your household, property details (such as roof year, square footage, and year built), and information about your current insurance coverage (carrier name and premium amount).</p>
          <p>We may also collect information about your browsing behavior on our website, including pages visited, time spent on pages, and referring URLs, through standard web analytics tools.</p>

          <h2 style={{ color: '#0f172a', fontSize: '22px', fontWeight: 700, margin: '32px 0 12px' }}>How We Use Your Information</h2>
          <p>We use the information you provide to:</p>
          <p style={{ paddingLeft: '16px' }}>
            <strong>Obtain insurance quotes</strong> — We share your information with our insurance carrier partners solely for the purpose of generating personalized insurance quotes on your behalf.<br /><br />
            <strong>Contact you</strong> — We may contact you by phone, email, or text message to discuss your quote request, provide quotes, answer questions, and assist with policy placement.<br /><br />
            <strong>Improve our services</strong> — We use aggregated, anonymized data to improve our website, services, and customer experience.<br /><br />
            <strong>AI coverage analysis</strong> — When you upload declarations pages, our AI technology analyzes the document to identify coverage gaps and savings opportunities. The uploaded documents are processed securely and used only for the purpose of generating your coverage analysis.
          </p>

          <h2 style={{ color: '#0f172a', fontSize: '22px', fontWeight: 700, margin: '32px 0 12px' }}>Information Sharing</h2>
          <p>We share your personal information only in the following circumstances:</p>
          <p style={{ paddingLeft: '16px' }}>
            <strong>Insurance carrier partners</strong> — We share your information with insurance carriers in our network for the purpose of obtaining quotes. These carriers are bound by their own privacy policies and applicable state and federal regulations.<br /><br />
            <strong>Service providers</strong> — We use third-party service providers for email delivery, data processing, and analytics. These providers are contractually obligated to use your data only for the services they provide to us.<br /><br />
            <strong>Legal requirements</strong> — We may disclose information when required by law, subpoena, or to protect our rights.
          </p>
          <p><strong>We do not sell your personal information to third parties.</strong> We do not share your information with unrelated companies for their own marketing purposes.</p>

          <h2 style={{ color: '#0f172a', fontSize: '22px', fontWeight: 700, margin: '32px 0 12px' }}>Remarketing & Communications</h2>
          <p>By submitting a quote request, you consent to receive follow-up communications from Better Choice Insurance Group regarding your quote, policy options, and related insurance information. This may include phone calls, emails, and text messages.</p>
          <p>We may use remarketing tools (such as website cookies and tracking pixels) to display relevant advertisements to you on other websites and platforms after you visit our site. You can opt out of remarketing by adjusting your browser cookie settings or using the opt-out mechanisms provided by advertising platforms.</p>
          <p>You may opt out of marketing communications at any time by contacting us at <a href="mailto:service@betterchoiceins.com" style={{ color: '#2563eb' }}>service@betterchoiceins.com</a> or calling <a href="tel:8479085665" style={{ color: '#2563eb' }}>(847) 908-5665</a>.</p>

          <h2 style={{ color: '#0f172a', fontSize: '22px', fontWeight: 700, margin: '32px 0 12px' }}>Data Security</h2>
          <p>We implement industry-standard security measures to protect your personal information, including encryption of data in transit and at rest, secure server infrastructure, and access controls limiting data access to authorized personnel only.</p>

          <h2 style={{ color: '#0f172a', fontSize: '22px', fontWeight: 700, margin: '32px 0 12px' }}>Data Retention</h2>
          <p>We retain your personal information for as long as necessary to fulfill the purposes described in this policy, comply with legal obligations, and resolve disputes. Quote request data is retained for up to 36 months. You may request deletion of your data at any time by contacting us.</p>

          <h2 style={{ color: '#0f172a', fontSize: '22px', fontWeight: 700, margin: '32px 0 12px' }}>Your Rights</h2>
          <p>You have the right to access, correct, or delete your personal information. You may also request a copy of the data we hold about you. To exercise these rights, contact us at <a href="mailto:service@betterchoiceins.com" style={{ color: '#2563eb' }}>service@betterchoiceins.com</a>.</p>

          <h2 style={{ color: '#0f172a', fontSize: '22px', fontWeight: 700, margin: '32px 0 12px' }}>Contact Us</h2>
          <p>
            Better Choice Insurance Group<br />
            Email: <a href="mailto:service@betterchoiceins.com" style={{ color: '#2563eb' }}>service@betterchoiceins.com</a><br />
            Phone: <a href="tel:8479085665" style={{ color: '#2563eb' }}>(847) 908-5665</a>
          </p>

          <div style={{ marginTop: '48px', paddingTop: '24px', borderTop: '1px solid #e5e7eb', textAlign: 'center' as const }}>
            <a href="/get-quote" style={{ color: '#2563eb', fontWeight: 700, textDecoration: 'none', fontSize: '16px' }}>
              ← Back to Get Your Quote
            </a>
          </div>
        </div>
      </div>
    </>
  );
}
