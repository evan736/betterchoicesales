import React, { useState } from 'react';

const CARRIERS: Record<string, any> = {
  progressive: {
    display_name: "Progressive Insurance",
    logo_color: "#0033A0",
    mobile_app_url: "https://www.progressive.com/app/",
    mobile_app_name: "Progressive App",
    online_account_url: "https://www.progressive.com/register/",
    online_account_text: "Create Your Progressive Account",
    claims_phone: "1-800-776-4737",
    roadside_phone: "1-800-776-4737",
    payment_url: "https://www.progressive.com/pay-bill/",
    extra_tip: "Download the Progressive app to get your digital ID card, track claims, and manage your policy.",
  },
  national_general: {
    display_name: "National General Insurance",
    logo_color: "#003366",
    mobile_app_url: "https://www.nationalgeneral.com/about/mobile-app",
    mobile_app_name: "National General Insurance App",
    online_account_url: "https://www.nationalgeneral.com/manage-your-policy",
    online_account_text: "Set Up Your Online Account",
    claims_phone: "1-800-325-1088",
    roadside_phone: "1-877-468-3466",
    payment_url: "https://www.nationalgeneral.com/make-a-payment",
    extra_tip: "You can manage your policy, view ID cards, and make payments right from the app.",
  },
  safeco: {
    display_name: "Safeco Insurance",
    logo_color: "#00529B",
    mobile_app_url: "https://www.safeco.com/about/mobile",
    mobile_app_name: "Safeco Mobile App",
    online_account_url: "https://www.safeco.com/manage-your-policy",
    online_account_text: "Set Up Your Safeco Account",
    claims_phone: "1-800-332-3226",
    roadside_phone: "1-877-762-3101",
    payment_url: "https://www.safeco.com/manage-your-policy",
    extra_tip: "The Safeco app lets you view ID cards, file claims, and contact roadside assistance instantly.",
  },
  travelers: {
    display_name: "Travelers Insurance",
    logo_color: "#E31837",
    mobile_app_url: "https://www.travelers.com/tools-resources/apps/mytravelers",
    mobile_app_name: "MyTravelers App",
    online_account_url: "https://www.travelers.com/online-account-access",
    online_account_text: "Create Your MyTravelers Account",
    claims_phone: "1-800-252-4633",
    roadside_phone: "1-800-252-4633",
    payment_url: "https://www.travelers.com/pay-your-bill",
    extra_tip: "With MyTravelers, you can view policy documents, report claims, and manage billing all in one place.",
  },
  grange: {
    display_name: "Grange Insurance",
    logo_color: "#1B5E20",
    mobile_app_url: "https://www.grangeinsurance.com/manage-your-policy/download-our-app",
    mobile_app_name: "Grange Mobile App",
    online_account_url: "https://www.grangeinsurance.com/manage-your-policy",
    online_account_text: "Set Up Your Grange Online Account",
    claims_phone: "1-800-445-3030",
    roadside_phone: "1-800-445-3030",
    payment_url: "https://www.grangeinsurance.com/manage-your-policy/pay-my-bill",
    extra_tip: "The Grange app gives you instant access to ID cards, claims filing, and payment options.",
  },
};

const EmailPreviewPage = () => {
  const [carrier, setCarrier] = useState('progressive');
  const info = CARRIERS[carrier];

  const clientName = "Sarah";
  const policyNumber = "PAH-9284710";
  const producerName = "Evan Larson";
  const policyType = "Auto";

  return (
    <div style={{ minHeight: '100vh', background: '#e2e8f0', fontFamily: '-apple-system, BlinkMacSystemFont, Segoe UI, Roboto, sans-serif' }}>
      {/* Carrier Switcher */}
      <div style={{ position: 'sticky', top: 0, zIndex: 50, background: '#1e293b', padding: '12px 20px', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <span style={{ color: '#fff', fontWeight: 700, fontSize: 14 }}>📧 Welcome Email Preview</span>
        <div style={{ display: 'flex', gap: 6 }}>
          {Object.entries(CARRIERS).map(([key, c]) => (
            <button
              key={key}
              onClick={() => setCarrier(key)}
              style={{
                padding: '6px 14px',
                borderRadius: 8,
                border: 'none',
                fontSize: 13,
                fontWeight: 600,
                cursor: 'pointer',
                background: carrier === key ? c.logo_color : '#475569',
                color: '#fff',
                transition: 'all 0.2s',
              }}
            >
              {c.display_name.split(' ')[0]}
            </button>
          ))}
        </div>
      </div>

      {/* Email Container */}
      <div style={{ maxWidth: 620, margin: '24px auto', padding: '0 16px 40px' }}>
        {/* Subject Line Preview */}
        <div style={{ background: '#fff', borderRadius: '12px 12px 0 0', padding: '16px 20px', borderBottom: '1px solid #e2e8f0' }}>
          <div style={{ fontSize: 11, color: '#94a3b8', marginBottom: 4 }}>SUBJECT</div>
          <div style={{ fontSize: 15, fontWeight: 600, color: '#1e293b' }}>
            Welcome to {info.display_name}! Your policy is ready 🎉
          </div>
          <div style={{ fontSize: 12, color: '#94a3b8', marginTop: 6 }}>
            From: Better Choice Insurance &lt;welcome@betterchoiceins.com&gt;
          </div>
          <div style={{ fontSize: 12, color: '#94a3b8' }}>
            To: sarah.johnson@email.com
          </div>
        </div>

        {/* Actual Email Body */}
        <div style={{ background: '#f1f5f9', padding: 0 }}>
          <div style={{ maxWidth: 600, margin: '0 auto', padding: 0 }}>
            
            {/* Header */}
            <div style={{
              background: `linear-gradient(135deg, ${info.logo_color}, #1e293b)`,
              padding: '32px 24px',
              textAlign: 'center' as const,
            }}>
              <h1 style={{ color: '#ffffff', margin: 0, fontSize: 28, fontWeight: 700 }}>Welcome, {clientName}! 🎉</h1>
              <p style={{ color: 'rgba(255,255,255,0.85)', margin: '8px 0 0', fontSize: 16 }}>Your {info.display_name} policy is all set</p>
            </div>

            {/* Body */}
            <div style={{ background: '#ffffff', padding: '32px 24px' }}>
              
              {/* Policy Info Card */}
              <div style={{ background: '#f8fafc', border: '1px solid #e2e8f0', borderRadius: 12, padding: 20, marginBottom: 24 }}>
                <h2 style={{ margin: '0 0 12px', fontSize: 16, color: '#64748b', fontWeight: 600 }}>YOUR POLICY DETAILS</h2>
                <table style={{ width: '100%', fontSize: 15, color: '#334155' }}>
                  <tbody>
                    <tr>
                      <td style={{ padding: '6px 0', color: '#94a3b8', width: 140 }}>Policy Number</td>
                      <td style={{ padding: '6px 0', fontWeight: 700, fontSize: 17, color: info.logo_color }}>{policyNumber}</td>
                    </tr>
                    <tr>
                      <td style={{ padding: '6px 0', color: '#94a3b8' }}>Carrier</td>
                      <td style={{ padding: '6px 0', fontWeight: 600 }}>{info.display_name}</td>
                    </tr>
                    <tr>
                      <td style={{ padding: '6px 0', color: '#94a3b8' }}>Coverage Type</td>
                      <td style={{ padding: '6px 0', fontWeight: 600 }}>{policyType}</td>
                    </tr>
                    <tr>
                      <td style={{ padding: '6px 0', color: '#94a3b8' }}>Your Agent</td>
                      <td style={{ padding: '6px 0', fontWeight: 600 }}>{producerName}</td>
                    </tr>
                  </tbody>
                </table>
              </div>

              {/* Getting Started */}
              <h2 style={{ margin: '0 0 16px', fontSize: 18, color: '#1e293b' }}>Get Started with {info.display_name}</h2>

              {/* Action Buttons */}
              <div style={{ marginBottom: 12 }}>
                <div style={{
                  display: 'block', background: info.logo_color, color: '#ffffff', padding: '14px 24px',
                  borderRadius: 10, textDecoration: 'none', fontWeight: 600, fontSize: 15, textAlign: 'center' as const, marginBottom: 10, cursor: 'pointer'
                }}>
                  🌐 {info.online_account_text}
                </div>

                <div style={{
                  display: 'block', background: '#059669', color: '#ffffff', padding: '14px 24px',
                  borderRadius: 10, textDecoration: 'none', fontWeight: 600, fontSize: 15, textAlign: 'center' as const, marginBottom: 10, cursor: 'pointer'
                }}>
                  📱 Download the {info.mobile_app_name}
                </div>

                <div style={{
                  display: 'block', background: '#475569', color: '#ffffff', padding: '14px 24px',
                  borderRadius: 10, textDecoration: 'none', fontWeight: 600, fontSize: 15, textAlign: 'center' as const, marginBottom: 10, cursor: 'pointer'
                }}>
                  💳 Make a Payment
                </div>
              </div>

              {/* Pro Tip */}
              <p style={{ color: '#64748b', fontSize: 14, margin: '16px 0', padding: '12px 16px', background: '#f0fdf4', borderRadius: 8, borderLeft: '4px solid #22c55e' }}>
                💡 <strong>Pro Tip:</strong> {info.extra_tip}
              </p>

              {/* Important Numbers */}
              <div style={{ margin: '24px 0', padding: 16, background: '#fafbfc', borderRadius: 10, border: '1px solid #e2e8f0' }}>
                <h3 style={{ margin: '0 0 10px', fontSize: 14, color: '#64748b', fontWeight: 600 }}>IMPORTANT NUMBERS</h3>
                <table style={{ width: '100%', fontSize: 14, color: '#334155' }}>
                  <tbody>
                    <tr>
                      <td style={{ padding: '4px 0', color: '#94a3b8' }}>Claims</td>
                      <td style={{ padding: '4px 0', fontWeight: 600 }}>{info.claims_phone}</td>
                    </tr>
                    <tr>
                      <td style={{ padding: '4px 0', color: '#94a3b8' }}>Roadside Assistance</td>
                      <td style={{ padding: '4px 0', fontWeight: 600 }}>{info.roadside_phone}</td>
                    </tr>
                    <tr>
                      <td style={{ padding: '4px 0', color: '#94a3b8' }}>Your Agent</td>
                      <td style={{ padding: '4px 0', fontWeight: 600 }}>{producerName} at Better Choice Insurance</td>
                    </tr>
                  </tbody>
                </table>
              </div>

              {/* Divider */}
              <hr style={{ border: 'none', borderTop: '1px solid #e2e8f0', margin: '28px 0' }} />

              {/* Survey CTA */}
              <div style={{ textAlign: 'center' as const, padding: 20, background: '#faf5ff', borderRadius: 12 }}>
                <h3 style={{ margin: '0 0 8px', fontSize: 18, color: '#7c3aed' }}>How did Evan do?</h3>
                <p style={{ color: '#64748b', fontSize: 14, margin: '0 0 16px' }}>Your feedback takes just 5 seconds — tap a star below!</p>
                <div>
                  {[1,2,3,4,5].map(i => (
                    <span key={i} style={{ fontSize: 32, padding: '0 4px', cursor: 'pointer' }}>⭐</span>
                  ))}
                </div>
              </div>
            </div>

            {/* Footer */}
            <div style={{ textAlign: 'center' as const, padding: '24px 0', color: '#94a3b8', fontSize: 12, background: '#f1f5f9' }}>
              <p style={{ margin: '4px 0' }}>Better Choice Insurance</p>
              <p style={{ margin: '4px 0' }}>Thank you for choosing us!</p>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default EmailPreviewPage;
