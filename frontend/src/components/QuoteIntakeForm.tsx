import React, { useState, useEffect, useCallback } from 'react';
import { Home, Car, Shield, ChevronRight, ChevronLeft, CheckCircle, User, MapPin, Calendar, DollarSign, Plus, X, Lock } from 'lucide-react';

// Types
interface Driver {
  name: string;
  dob: string;
  relationship: string;
}

interface QuoteFormData {
  // Step 1: Products
  products: string[];
  // Step 2: Contact
  firstName: string;
  lastName: string;
  email: string;
  phone: string;
  dob: string;
  // Step 3: Address
  address: string;
  city: string;
  state: string;
  zip: string;
  // Step 4: Property (if home)
  roofYear: string;
  homeYear: string;
  sqft: string;
  // Step 5: Drivers (if auto)
  drivers: Driver[];
  // Step 6: Current coverage
  currentCarrier: string;
  currentPremium: string;
  // Privacy
  privacyConsent: boolean;
}

const INITIAL_FORM: QuoteFormData = {
  products: [],
  firstName: '', lastName: '', email: '', phone: '', dob: '',
  address: '', city: '', state: '', zip: '',
  roofYear: '', homeYear: '', sqft: '',
  drivers: [{ name: '', dob: '', relationship: 'Self' }],
  currentCarrier: '', currentPremium: '',
  privacyConsent: false,
};

const PRODUCTS = [
  { id: 'home', label: 'Home', icon: Home, desc: 'Homeowners insurance' },
  { id: 'auto', label: 'Auto', icon: Car, desc: 'Auto insurance' },
  { id: 'bundle', label: 'Bundle & Save', icon: Shield, desc: 'Home + Auto (save up to 25%)', highlight: true },
  { id: 'renters', label: 'Renters', icon: Home, desc: 'Renters insurance' },
  { id: 'landlord', label: 'Landlord', icon: Home, desc: 'Landlord / rental property' },
  { id: 'other', label: 'Other', icon: Shield, desc: 'Umbrella, specialty, etc.' },
];

const STATES = ['AL','AK','AZ','AR','CA','CO','CT','DE','FL','GA','HI','ID','IL','IN','IA','KS','KY','LA','ME','MD','MA','MI','MN','MS','MO','MT','NE','NV','NH','NJ','NM','NY','NC','ND','OH','OK','OR','PA','RI','SC','SD','TN','TX','UT','VT','VA','WA','WV','WI','WY'];

const CARRIERS = ['Allstate','American Family','Auto-Owners','Erie','Farmers','GEICO','Hartford','Liberty Mutual','Nationwide','Progressive','Safeco','State Farm','Travelers','USAA','Other','None / New Policy'];

interface QuoteIntakeFormProps {
  initialName?: string;
  policyType?: string;
  currentCarrier?: string;
  renewalDate?: string;
  utmCampaign?: string;
  onSubmit?: (data: QuoteFormData) => void;
}

export default function QuoteIntakeForm({ initialName, policyType, currentCarrier: initCarrier, renewalDate, utmCampaign, onSubmit }: QuoteIntakeFormProps) {
  const [form, setForm] = useState<QuoteFormData>(INITIAL_FORM);
  const [step, setStep] = useState(0);
  const [submitted, setSubmitted] = useState(false);
  const [leadSent, setLeadSent] = useState(false);
  const [streetViewUrl, setStreetViewUrl] = useState('');
  const [addressSuggestions, setAddressSuggestions] = useState<string[]>([]);
  const [showSuggestions, setShowSuggestions] = useState(false);

  const API = process.env.NEXT_PUBLIC_API_URL || 'https://better-choice-api.onrender.com';

  // Pre-fill from URL params
  useEffect(() => {
    if (initialName) {
      const parts = initialName.split(' ');
      setForm(p => ({ ...p, firstName: parts[0] || '', lastName: parts.slice(1).join(' ') || '' }));
    }
    if (initCarrier) setForm(p => ({ ...p, currentCarrier: initCarrier }));
    if (policyType) {
      const pt = policyType.toLowerCase();
      if (pt.includes('bundle') || (pt.includes('home') && pt.includes('auto'))) {
        setForm(p => ({ ...p, products: ['bundle'] }));
      } else if (pt.includes('home')) {
        setForm(p => ({ ...p, products: ['home'] }));
      } else if (pt.includes('auto')) {
        setForm(p => ({ ...p, products: ['auto'] }));
      }
    }
  }, [initialName, initCarrier, policyType]);

  const needsHome = form.products.some(p => ['home', 'bundle', 'landlord'].includes(p));
  const needsAuto = form.products.some(p => ['auto', 'bundle'].includes(p));

  // Build steps dynamically based on product selection
  const steps = [
    'products',    // 0: What do you need?
    'contact',     // 1: Your info
    'address',     // 2: Address
    ...(needsHome ? ['property'] : []),   // 3?: Property details
    ...(needsAuto ? ['drivers'] : []),    // 4?: Driver info
    'coverage',    // Last: Current coverage + submit
  ];

  const totalSteps = steps.length;
  const currentStepType = steps[step];
  const progress = ((step + 1) / totalSteps) * 100;

  // Send partial lead at key steps
  const sendPartialLead = useCallback(async (extraData?: Record<string, any>) => {
    if (leadSent && !extraData) return;
    if (!form.firstName && !form.phone) return;
    try {
      await fetch(`${API}/api/campaigns/landing-lead`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: `${form.firstName} ${form.lastName}`.trim(),
          phone: form.phone,
          email: form.email,
          message: `[Quote Form] Products: ${form.products.join(', ')}. Address: ${form.address} ${form.city} ${form.state} ${form.zip}. DOB: ${form.dob}. ${needsAuto ? `Drivers: ${form.drivers.map(d => d.name).join(', ')}.` : ''} ${needsHome ? `Roof: ${form.roofYear}. Built: ${form.homeYear}. Sqft: ${form.sqft}.` : ''} Current: ${form.currentCarrier} @ ${form.currentPremium}/yr. ${extraData ? JSON.stringify(extraData) : ''}`,
          policy_type: form.products.join(', '),
          current_carrier: form.currentCarrier,
          renewal_date: renewalDate || '',
          utm_campaign: utmCampaign || 'quote_form',
          source: 'quote_intake_form',
          ...extraData,
        }),
      });
      setLeadSent(true);
    } catch (e) { /* ok */ }
  }, [form, API, leadSent, needsAuto, needsHome, renewalDate, utmCampaign]);

  // Address autocomplete (simple version using input events)
  const handleAddressChange = (value: string) => {
    setForm(p => ({ ...p, address: value }));
    // We'll rely on browser autocomplete for now
    // A Google Places autocomplete could be added later
  };

  // Generate street view URL when we have a full address
  useEffect(() => {
    if (form.address && form.city && form.state && form.zip) {
      const addr = encodeURIComponent(`${form.address}, ${form.city}, ${form.state} ${form.zip}`);
      setStreetViewUrl(`https://maps.googleapis.com/maps/api/streetview?size=400x250&location=${addr}&key=&source=outdoor`);
    }
  }, [form.address, form.city, form.state, form.zip]);

  const canAdvance = () => {
    switch (currentStepType) {
      case 'products': return form.products.length > 0;
      case 'contact': return form.firstName && form.phone;
      case 'address': return form.address && form.city && form.state && form.zip;
      case 'property': return true; // optional fields
      case 'drivers': return true; // optional fields
      case 'coverage': return form.privacyConsent;
      default: return true;
    }
  };

  const handleNext = () => {
    if (step === 1) { // After contact info, send partial lead
      sendPartialLead();
    }
    if (step < totalSteps - 1) setStep(s => s + 1);
  };

  const handleSubmit = async () => {
    setSubmitted(true);
    await sendPartialLead({ step: 'final_submit' });
    onSubmit?.(form);
  };

  const handleProductToggle = (id: string) => {
    setForm(p => {
      let products = [...p.products];
      if (id === 'bundle') {
        // Bundle replaces individual home/auto
        if (products.includes('bundle')) {
          products = products.filter(x => x !== 'bundle');
        } else {
          products = products.filter(x => !['home', 'auto'].includes(x));
          products.push('bundle');
        }
      } else if (['home', 'auto'].includes(id) && products.includes('bundle')) {
        // If bundle is selected and they click home/auto, switch to individual
        products = products.filter(x => x !== 'bundle');
        products.push(id);
      } else {
        if (products.includes(id)) {
          products = products.filter(x => x !== id);
        } else {
          products.push(id);
        }
      }
      // Auto-suggest bundle
      if (products.includes('home') && products.includes('auto')) {
        products = products.filter(x => !['home', 'auto'].includes(x));
        products.push('bundle');
      }
      return { ...p, products };
    });
  };

  const addDriver = () => {
    setForm(p => ({ ...p, drivers: [...p.drivers, { name: '', dob: '', relationship: '' }] }));
  };

  const removeDriver = (idx: number) => {
    if (idx === 0) return;
    setForm(p => ({ ...p, drivers: p.drivers.filter((_, i) => i !== idx) }));
  };

  const updateDriver = (idx: number, field: keyof Driver, value: string) => {
    setForm(p => {
      const drivers = [...p.drivers];
      drivers[idx] = { ...drivers[idx], [field]: value };
      return { ...p, drivers };
    });
  };

  // Styles
  const iS: React.CSSProperties = {
    width: '100%', padding: '12px 16px', fontSize: '15px', borderRadius: '8px',
    border: '1px solid rgba(255,255,255,0.15)', background: 'rgba(255,255,255,0.06)',
    color: '#fff', outline: 'none', boxSizing: 'border-box',
    fontFamily: "'DM Sans', sans-serif",
  };
  const lS: React.CSSProperties = { display: 'block', color: '#94a3b8', fontSize: '13px', fontWeight: 600, marginBottom: '6px' };

  if (submitted) {
    return (
      <div style={{ textAlign: 'center', padding: '48px 32px' }}>
        <CheckCircle size={56} color="#22c55e" style={{ marginBottom: '16px' }} />
        <h3 style={{ color: '#fff', fontSize: '24px', fontWeight: 700, margin: '0 0 12px' }}>Your quote request is in!</h3>
        <p style={{ color: '#94a3b8', fontSize: '16px', lineHeight: 1.6, margin: '0 0 8px', maxWidth: '400px', marginLeft: 'auto', marginRight: 'auto' }}>
          A licensed agent will review your information and reach out within one business day with personalized rate comparisons from 15+ carriers.
        </p>
        <p style={{ color: '#64748b', fontSize: '14px', margin: '24px 0 0' }}>
          Need faster help? Call <a href="tel:8479085665" style={{ color: '#60a5fa', fontWeight: 700, textDecoration: 'none' }}>(847) 908-5665</a>
        </p>
      </div>
    );
  }

  return (
    <div>
      {/* Progress bar */}
      <div style={{ marginBottom: '28px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '8px' }}>
          <span style={{ color: '#94a3b8', fontSize: '13px', fontWeight: 600 }}>Step {step + 1} of {totalSteps}</span>
          <span style={{ color: '#64748b', fontSize: '13px' }}>{Math.round(progress)}%</span>
        </div>
        <div style={{ height: '4px', background: 'rgba(255,255,255,0.08)', borderRadius: '2px', overflow: 'hidden' }}>
          <div style={{ height: '100%', width: `${progress}%`, background: 'linear-gradient(90deg, #2563eb, #34d399)', borderRadius: '2px', transition: 'width 0.4s ease' }} />
        </div>
      </div>

      {/* ── Step: Products ── */}
      {currentStepType === 'products' && (
        <div>
          <h3 style={{ color: '#fff', fontSize: '20px', fontWeight: 700, margin: '0 0 4px' }}>What would you like to quote?</h3>
          <p style={{ color: '#94a3b8', fontSize: '14px', margin: '0 0 24px' }}>Select all that apply. Bundling saves up to 25%!</p>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(160px, 1fr))', gap: '12px' }}>
            {PRODUCTS.map(p => {
              const Icon = p.icon;
              const selected = form.products.includes(p.id);
              return (
                <button key={p.id} onClick={() => handleProductToggle(p.id)} style={{
                  background: selected ? (p.highlight ? 'rgba(16,185,129,0.15)' : 'rgba(37,99,235,0.15)') : 'rgba(255,255,255,0.04)',
                  border: selected ? `2px solid ${p.highlight ? 'rgba(16,185,129,0.5)' : 'rgba(37,99,235,0.5)'}` : '2px solid rgba(255,255,255,0.08)',
                  borderRadius: '12px', padding: '16px 12px', cursor: 'pointer', textAlign: 'left' as const,
                  transition: 'all 0.2s', position: 'relative',
                }}>
                  {p.highlight && (
                    <div style={{ position: 'absolute', top: '-8px', right: '8px', background: '#10b981', color: '#fff', fontSize: '10px', fontWeight: 800, padding: '2px 8px', borderRadius: '10px', letterSpacing: '0.5px' }}>
                      BEST VALUE
                    </div>
                  )}
                  <Icon size={24} style={{ color: selected ? (p.highlight ? '#34d399' : '#60a5fa') : '#64748b', marginBottom: '8px' }} />
                  <div style={{ color: '#fff', fontSize: '15px', fontWeight: 700 }}>{p.label}</div>
                  <div style={{ color: '#64748b', fontSize: '12px', marginTop: '2px' }}>{p.desc}</div>
                  {selected && (
                    <div style={{ position: 'absolute', top: '8px', left: '8px' }}>
                      <CheckCircle size={16} style={{ color: p.highlight ? '#34d399' : '#60a5fa' }} />
                    </div>
                  )}
                </button>
              );
            })}
          </div>
        </div>
      )}

      {/* ── Step: Contact Info ── */}
      {currentStepType === 'contact' && (
        <div>
          <h3 style={{ color: '#fff', fontSize: '20px', fontWeight: 700, margin: '0 0 4px' }}>Tell us about yourself</h3>
          <p style={{ color: '#94a3b8', fontSize: '14px', margin: '0 0 24px' }}>We need a few details to get your quotes.</p>
          <div style={{ display: 'flex', gap: '12px', marginBottom: '16px' }}>
            <div style={{ flex: 1 }}>
              <label style={lS}>First Name <span style={{ color: '#f87171' }}>*</span></label>
              <input style={iS} value={form.firstName} placeholder="John"
                onChange={e => setForm(p => ({ ...p, firstName: e.target.value }))} />
            </div>
            <div style={{ flex: 1 }}>
              <label style={lS}>Last Name</label>
              <input style={iS} value={form.lastName} placeholder="Smith"
                onChange={e => setForm(p => ({ ...p, lastName: e.target.value }))} />
            </div>
          </div>
          <div style={{ marginBottom: '16px' }}>
            <label style={lS}>Phone <span style={{ color: '#f87171' }}>*</span></label>
            <input style={iS} type="tel" value={form.phone} placeholder="(555) 123-4567"
              onChange={e => setForm(p => ({ ...p, phone: e.target.value }))} />
          </div>
          <div style={{ marginBottom: '16px' }}>
            <label style={lS}>Email</label>
            <input style={iS} type="email" value={form.email} placeholder="john@example.com"
              onChange={e => setForm(p => ({ ...p, email: e.target.value }))} />
          </div>
          <div>
            <label style={lS}>Date of Birth</label>
            <input style={iS} type="date" value={form.dob}
              onChange={e => setForm(p => ({ ...p, dob: e.target.value }))} />
          </div>
        </div>
      )}

      {/* ── Step: Address ── */}
      {currentStepType === 'address' && (
        <div>
          <h3 style={{ color: '#fff', fontSize: '20px', fontWeight: 700, margin: '0 0 4px' }}>
            {needsHome ? 'Where is the property?' : 'What is your address?'}
          </h3>
          <p style={{ color: '#94a3b8', fontSize: '14px', margin: '0 0 24px' }}>This helps us find the most accurate rates for your area.</p>
          <div style={{ marginBottom: '16px', position: 'relative' }}>
            <label style={lS}>Street Address <span style={{ color: '#f87171' }}>*</span></label>
            <input style={iS} value={form.address} placeholder="123 Main Street"
              autoComplete="street-address"
              onChange={e => handleAddressChange(e.target.value)} />
          </div>
          <div style={{ display: 'flex', gap: '12px', marginBottom: '16px' }}>
            <div style={{ flex: 2 }}>
              <label style={lS}>City <span style={{ color: '#f87171' }}>*</span></label>
              <input style={iS} value={form.city} placeholder="Chicago"
                autoComplete="address-level2"
                onChange={e => setForm(p => ({ ...p, city: e.target.value }))} />
            </div>
            <div style={{ flex: 1 }}>
              <label style={lS}>State <span style={{ color: '#f87171' }}>*</span></label>
              <select style={{ ...iS, appearance: 'none' as const }} value={form.state}
                onChange={e => setForm(p => ({ ...p, state: e.target.value }))}>
                <option value="">--</option>
                {STATES.map(s => <option key={s} value={s}>{s}</option>)}
              </select>
            </div>
            <div style={{ flex: 1 }}>
              <label style={lS}>ZIP <span style={{ color: '#f87171' }}>*</span></label>
              <input style={iS} value={form.zip} placeholder="60601" maxLength={5}
                autoComplete="postal-code"
                onChange={e => setForm(p => ({ ...p, zip: e.target.value }))} />
            </div>
          </div>
        </div>
      )}

      {/* ── Step: Property Details ── */}
      {currentStepType === 'property' && (
        <div>
          <h3 style={{ color: '#fff', fontSize: '20px', fontWeight: 700, margin: '0 0 4px' }}>Property Details</h3>
          <p style={{ color: '#94a3b8', fontSize: '14px', margin: '0 0 24px' }}>These help us find the most competitive home rates. Skip any you don&apos;t know.</p>
          <div style={{ display: 'flex', gap: '12px', marginBottom: '16px' }}>
            <div style={{ flex: 1 }}>
              <label style={lS}>Year Roof Installed/Replaced</label>
              <input style={iS} value={form.roofYear} placeholder="e.g. 2018" maxLength={4}
                onChange={e => setForm(p => ({ ...p, roofYear: e.target.value }))} />
            </div>
            <div style={{ flex: 1 }}>
              <label style={lS}>Year Home Built</label>
              <input style={iS} value={form.homeYear} placeholder="e.g. 1995" maxLength={4}
                onChange={e => setForm(p => ({ ...p, homeYear: e.target.value }))} />
            </div>
          </div>
          <div style={{ marginBottom: '16px' }}>
            <label style={lS}>Square Footage (approx.)</label>
            <input style={iS} value={form.sqft} placeholder="e.g. 2,200"
              onChange={e => setForm(p => ({ ...p, sqft: e.target.value }))} />
          </div>
          <p style={{ color: '#64748b', fontSize: '12px', margin: '8px 0 0', fontStyle: 'italic' }}>
            Don&apos;t worry if you don&apos;t have these — our agent can look them up.
          </p>
        </div>
      )}

      {/* ── Step: Drivers ── */}
      {currentStepType === 'drivers' && (
        <div>
          <h3 style={{ color: '#fff', fontSize: '20px', fontWeight: 700, margin: '0 0 4px' }}>Drivers in the Household</h3>
          <p style={{ color: '#94a3b8', fontSize: '14px', margin: '0 0 24px' }}>List all licensed drivers in your household for the most accurate auto rates.</p>
          {form.drivers.map((driver, idx) => (
            <div key={idx} style={{
              background: 'rgba(255,255,255,0.04)', borderRadius: '12px', padding: '16px',
              border: '1px solid rgba(255,255,255,0.08)', marginBottom: '12px', position: 'relative',
            }}>
              {idx > 0 && (
                <button onClick={() => removeDriver(idx)} style={{
                  position: 'absolute', top: '8px', right: '8px', background: 'none', border: 'none',
                  color: '#64748b', cursor: 'pointer', padding: '4px',
                }}>
                  <X size={16} />
                </button>
              )}
              <div style={{ fontSize: '12px', color: '#64748b', fontWeight: 700, marginBottom: '10px', textTransform: 'uppercase' as const, letterSpacing: '0.5px' }}>
                {idx === 0 ? 'Primary Driver (You)' : `Driver ${idx + 1}`}
              </div>
              <div style={{ display: 'flex', gap: '12px', flexWrap: 'wrap' as const }}>
                <div style={{ flex: '2 1 180px' }}>
                  <label style={lS}>Full Name</label>
                  <input style={iS} value={driver.name} placeholder={idx === 0 ? `${form.firstName} ${form.lastName}`.trim() || 'Your name' : 'Driver name'}
                    onChange={e => updateDriver(idx, 'name', e.target.value)} />
                </div>
                <div style={{ flex: '1 1 140px' }}>
                  <label style={lS}>Date of Birth</label>
                  <input style={iS} type="date" value={driver.dob}
                    onChange={e => updateDriver(idx, 'dob', e.target.value)} />
                </div>
                {idx > 0 && (
                  <div style={{ flex: '1 1 140px' }}>
                    <label style={lS}>Relationship</label>
                    <select style={{ ...iS, appearance: 'none' as const }} value={driver.relationship}
                      onChange={e => updateDriver(idx, 'relationship', e.target.value)}>
                      <option value="">Select...</option>
                      <option value="Spouse">Spouse</option>
                      <option value="Child">Child</option>
                      <option value="Parent">Parent</option>
                      <option value="Other">Other</option>
                    </select>
                  </div>
                )}
              </div>
            </div>
          ))}
          <button onClick={addDriver} style={{
            display: 'flex', alignItems: 'center', gap: '6px', background: 'none',
            border: '1px dashed rgba(255,255,255,0.15)', borderRadius: '8px', padding: '10px 16px',
            color: '#60a5fa', fontSize: '14px', fontWeight: 600, cursor: 'pointer', width: '100%', justifyContent: 'center',
          }}>
            <Plus size={16} /> Add Another Driver
          </button>
        </div>
      )}

      {/* ── Step: Current Coverage + Submit ── */}
      {currentStepType === 'coverage' && (
        <div>
          <h3 style={{ color: '#fff', fontSize: '20px', fontWeight: 700, margin: '0 0 4px' }}>Almost done!</h3>
          <p style={{ color: '#94a3b8', fontSize: '14px', margin: '0 0 24px' }}>This helps us understand what to beat. Both fields are optional.</p>
          <div style={{ marginBottom: '16px' }}>
            <label style={lS}>Current Insurance Carrier</label>
            <select style={{ ...iS, appearance: 'none' as const }} value={form.currentCarrier}
              onChange={e => setForm(p => ({ ...p, currentCarrier: e.target.value }))}>
              <option value="">Select your carrier...</option>
              {CARRIERS.map(c => <option key={c} value={c}>{c}</option>)}
            </select>
          </div>
          <div style={{ marginBottom: '24px' }}>
            <label style={lS}>Current Annual Premium (approx.)</label>
            <div style={{ position: 'relative' }}>
              <span style={{ position: 'absolute', left: '16px', top: '50%', transform: 'translateY(-50%)', color: '#64748b', fontSize: '15px' }}>$</span>
              <input style={{ ...iS, paddingLeft: '28px' }} value={form.currentPremium} placeholder="e.g. 2,400"
                onChange={e => setForm(p => ({ ...p, currentPremium: e.target.value }))} />
            </div>
          </div>

          {/* Privacy consent */}
          <div style={{
            background: 'rgba(255,255,255,0.04)', borderRadius: '12px', padding: '16px',
            border: '1px solid rgba(255,255,255,0.08)', marginBottom: '20px',
          }}>
            <div style={{ display: 'flex', gap: '12px', alignItems: 'flex-start' }}>
              <input type="checkbox" checked={form.privacyConsent}
                onChange={e => setForm(p => ({ ...p, privacyConsent: e.target.checked }))}
                style={{ marginTop: '4px', accentColor: '#2563eb', width: '18px', height: '18px', flexShrink: 0 }}
              />
              <div>
                <p style={{ color: '#e2e8f0', fontSize: '13px', lineHeight: 1.6, margin: 0 }}>
                  I consent to Better Choice Insurance Group collecting and using the information provided to obtain insurance quotes on my behalf from their carrier partners. I understand my information may be shared with insurance carriers for the purpose of generating quotes, and that I may be contacted by phone, email, or text regarding my quote request.{' '}
                  <a href="#privacy" onClick={(e) => { e.preventDefault(); window.open('/privacy', '_blank'); }} style={{ color: '#60a5fa', textDecoration: 'underline' }}>Privacy Policy</a>
                </p>
              </div>
            </div>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: '#64748b', fontSize: '12px', marginBottom: '16px' }}>
            <Lock size={14} /> Your information is encrypted and never sold to third parties.
          </div>
        </div>
      )}

      {/* ── Navigation buttons ── */}
      <div style={{ display: 'flex', gap: '12px', marginTop: '28px' }}>
        {step > 0 && (
          <button onClick={() => setStep(s => s - 1)} style={{
            padding: '14px 20px', fontSize: '15px', fontWeight: 600,
            background: 'rgba(255,255,255,0.06)', color: '#94a3b8',
            border: '1px solid rgba(255,255,255,0.1)', borderRadius: '8px', cursor: 'pointer',
            display: 'flex', alignItems: 'center', gap: '6px', fontFamily: "'DM Sans', sans-serif",
          }}>
            <ChevronLeft size={18} /> Back
          </button>
        )}
        {currentStepType !== 'coverage' ? (
          <button onClick={handleNext} disabled={!canAdvance()} style={{
            flex: 1, padding: '14px', fontSize: '16px', fontWeight: 700,
            background: canAdvance() ? '#2563eb' : '#475569',
            color: '#fff', border: 'none', borderRadius: '8px', cursor: canAdvance() ? 'pointer' : 'default',
            display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '8px',
            fontFamily: "'DM Sans', sans-serif",
          }}>
            Continue <ChevronRight size={18} />
          </button>
        ) : (
          <button onClick={handleSubmit} disabled={!form.privacyConsent} style={{
            flex: 1, padding: '14px', fontSize: '16px', fontWeight: 700,
            background: form.privacyConsent ? '#2563eb' : '#475569',
            color: '#fff', border: 'none', borderRadius: '8px', cursor: form.privacyConsent ? 'pointer' : 'default',
            boxShadow: form.privacyConsent ? '0 4px 20px rgba(37,99,235,0.3)' : 'none',
            fontFamily: "'DM Sans', sans-serif",
          }}>
            Submit My Quote Request →
          </button>
        )}
      </div>
    </div>
  );
}
