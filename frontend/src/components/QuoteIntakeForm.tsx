import React, { useState, useEffect, useCallback } from 'react';
import { useRouter } from 'next/router';
import { Home, Car, Shield, ChevronRight, ChevronLeft, CheckCircle, Plus, X, Lock } from 'lucide-react';

interface Driver {
  name: string;
  dob: string;
  relationship: string;
}

interface Vehicle {
  year: string;
  make: string;
  model: string;
}

interface QuoteFormData {
  products: string[];
  firstName: string;
  lastName: string;
  email: string;
  phone: string;
  dob: string;
  address: string;
  city: string;
  state: string;
  zip: string;
  roofYear: string;
  homeYear: string;
  sqft: string;
  drivers: Driver[];
  vehicles: Vehicle[];
  currentCarrier: string;
  currentPremium: string;
  privacyConsent: boolean;
}

const INITIAL: QuoteFormData = {
  products: [],
  firstName: '', lastName: '', email: '', phone: '', dob: '',
  address: '', city: '', state: '', zip: '',
  roofYear: '', homeYear: '', sqft: '',
  drivers: [{ name: '', dob: '', relationship: 'Self' }],
  vehicles: [{ year: '', make: '', model: '' }],
  currentCarrier: '', currentPremium: '',
  privacyConsent: false,
};

const PRODUCTS = [
  { id: 'home', label: 'Home', icon: Home, desc: 'Homeowners insurance' },
  { id: 'bundle', label: 'Bundle & Save', icon: Shield, desc: 'Home + Auto (save up to 25%)', highlight: true },
  { id: 'auto', label: 'Auto', icon: Car, desc: 'Auto insurance' },
];

const STATES = ['AL','AK','AZ','AR','CA','CO','CT','DE','FL','GA','HI','ID','IL','IN','IA','KS','KY','LA','ME','MD','MA','MI','MN','MS','MO','MT','NE','NV','NH','NJ','NM','NY','NC','ND','OH','OK','OR','PA','RI','SC','SD','TN','TX','UT','VT','VA','WA','WV','WI','WY'];

const CARRIERS = ['Allstate','American Family','Auto-Owners','Erie','Farmers','GEICO','Grange','Hartford','Liberty Mutual','National General','Nationwide','Progressive','Safeco','State Farm','Travelers','USAA','Other','None / New Policy'];

interface Props {
  initialName?: string;
  policyType?: string;
  currentCarrier?: string;
  renewalDate?: string;
  utmCampaign?: string;
}

export default function QuoteIntakeForm({ initialName, policyType, currentCarrier: initCarrier, renewalDate, utmCampaign }: Props) {
  const router = useRouter();
  const [form, setForm] = useState<QuoteFormData>(INITIAL);
  const [step, setStep] = useState(0);
  const [leadSent, setLeadSent] = useState(false);

  const API = process.env.NEXT_PUBLIC_API_URL || 'https://better-choice-api.onrender.com';

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

  const needsHome = form.products.some(p => ['home', 'bundle'].includes(p));
  const needsAuto = form.products.some(p => ['auto', 'bundle'].includes(p));

  const steps = [
    'products',
    'contact',
    'address',
    ...(needsHome ? ['property'] : []),
    ...(needsAuto ? ['drivers', 'vehicles'] : []),
    'coverage',
  ];
  const totalSteps = steps.length;
  const currentStepType = steps[step];
  const progress = ((step + 1) / totalSteps) * 100;

  // Auto-populate first driver name/DOB from contact info
  useEffect(() => {
    if (form.firstName || form.lastName) {
      const fullName = `${form.firstName} ${form.lastName}`.trim();
      setForm(p => {
        const drivers = [...p.drivers];
        if (drivers[0]) {
          drivers[0] = { ...drivers[0], name: fullName, dob: p.dob };
        }
        return { ...p, drivers };
      });
    }
  }, [form.firstName, form.lastName, form.dob]);

  const sendLead = useCallback(async (extra?: Record<string, any>) => {
    if (!form.firstName && !form.phone) return;
    try {
      const driverInfo = form.drivers.filter(d => d.name).map(d => `${d.name} (DOB: ${d.dob || 'N/A'}, ${d.relationship || 'N/A'})`).join('; ');
      const vehicleInfo = form.vehicles.filter(v => v.year || v.make || v.model).map(v => `${v.year} ${v.make} ${v.model}`.trim()).join('; ');
      await fetch(`${API}/api/campaigns/landing-lead`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: `${form.firstName} ${form.lastName}`.trim(),
          phone: form.phone,
          email: form.email,
          message: [
            `[Quote Form${extra?.step === 'final_submit' ? ' - FINAL' : ' - Partial'}]`,
            `Products: ${form.products.join(', ')}`,
            `DOB: ${form.dob}`,
            `Address: ${form.address}, ${form.city}, ${form.state} ${form.zip}`,
            needsHome ? `Roof: ${form.roofYear || 'N/A'}, Built: ${form.homeYear || 'N/A'}, Sqft: ${form.sqft || 'N/A'}` : '',
            needsAuto ? `Drivers: ${driverInfo || 'N/A'}` : '',
            needsAuto ? `Vehicles: ${vehicleInfo || 'N/A'}` : '',
            `Current carrier: ${form.currentCarrier || 'N/A'}`,
            `Current premium: ${form.currentPremium ? '$' + form.currentPremium : 'N/A'}/yr`,
          ].filter(Boolean).join('\n'),
          policy_type: form.products.join(', '),
          current_carrier: form.currentCarrier,
          renewal_date: renewalDate || '',
          utm_campaign: utmCampaign || 'quote_form',
          source: 'quote_intake_form',
        }),
      });
      setLeadSent(true);
    } catch (e) { /* ok */ }
  }, [form, API, needsAuto, needsHome, renewalDate, utmCampaign]);

  const handleProductToggle = (id: string) => {
    setForm(p => {
      let products = [...p.products];
      if (id === 'bundle') {
        products = products.includes('bundle') ? [] : ['bundle'];
      } else if (products.includes('bundle')) {
        products = [id];
      } else {
        products = products.includes(id) ? products.filter(x => x !== id) : [...products, id];
      }
      // Auto-bundle if both selected
      if (products.includes('home') && products.includes('auto')) {
        products = ['bundle'];
      }
      return { ...p, products };
    });
  };

  const canAdvance = () => {
    switch (currentStepType) {
      case 'products': return form.products.length > 0;
      case 'contact': return form.firstName && form.phone;
      case 'address': return form.address && form.city && form.state && form.zip;
      case 'property': return true;
      case 'drivers': return true;
      case 'coverage': return form.privacyConsent;
      default: return true;
    }
  };

  const handleNext = () => {
    if (step < totalSteps - 1) setStep(s => s + 1);
  };

  const handleSubmit = async () => {
    await sendLead({ step: 'final_submit' });
    // Navigate to confirmation page
    const params = new URLSearchParams({
      name: form.firstName,
      products: form.products.join(','),
    });
    router.push(`/quote-confirmation?${params.toString()}`);
  };

  const addDriver = () => setForm(p => ({ ...p, drivers: [...p.drivers, { name: '', dob: '', relationship: '' }] }));
  const removeDriver = (i: number) => { if (i > 0) setForm(p => ({ ...p, drivers: p.drivers.filter((_, j) => j !== i) })); };
  const addVehicle = () => setForm(p => ({ ...p, vehicles: [...p.vehicles, { year: '', make: '', model: '' }] }));
  const removeVehicle = (i: number) => { if (i > 0) setForm(p => ({ ...p, vehicles: p.vehicles.filter((_, j) => j !== i) })); };
  const updateVehicle = (i: number, field: keyof Vehicle, val: string) => {
    setForm(p => ({ ...p, vehicles: p.vehicles.map((v, j) => j === i ? { ...v, [field]: val } : v) }));
  };
  const updateDriver = (i: number, f: keyof Driver, v: string) => {
    setForm(p => { const d = [...p.drivers]; d[i] = { ...d[i], [f]: v }; return { ...p, drivers: d }; });
  };

  // Current year for roof age calculation
  const currentYear = new Date().getFullYear();
  const roofAge = form.roofYear ? currentYear - parseInt(form.roofYear) : null;

  // Input styles
  const iS: React.CSSProperties = {
    width: '100%', padding: '12px 16px', fontSize: '15px', borderRadius: '8px',
    border: '1px solid rgba(255,255,255,0.15)', background: 'rgba(255,255,255,0.06)',
    color: '#fff', outline: 'none', boxSizing: 'border-box',
    fontFamily: "'DM Sans', sans-serif",
  };
  const selS: React.CSSProperties = {
    ...iS, appearance: 'none' as const,
    backgroundImage: `url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 24 24' fill='none' stroke='%2394a3b8' stroke-width='2'%3E%3Cpath d='M6 9l6 6 6-6'/%3E%3C/svg%3E")`,
    backgroundRepeat: 'no-repeat', backgroundPosition: 'right 12px center',
  };
  const optS: React.CSSProperties = { color: '#1a1a2e', background: '#fff' };
  const lS: React.CSSProperties = { display: 'block', color: '#94a3b8', fontSize: '13px', fontWeight: 600, marginBottom: '6px' };

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

      {/* ── Products ── */}
      {currentStepType === 'products' && (
        <div>
          <h3 style={{ color: '#fff', fontSize: '20px', fontWeight: 700, margin: '0 0 4px' }}>What would you like to quote?</h3>
          <p style={{ color: '#94a3b8', fontSize: '14px', margin: '0 0 24px' }}>Bundling home &amp; auto saves up to 25%!</p>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '12px' }}>
            {PRODUCTS.map(p => {
              const Icon = p.icon;
              const sel = form.products.includes(p.id);
              return (
                <button key={p.id} onClick={() => handleProductToggle(p.id)} style={{
                  background: sel ? (p.highlight ? 'rgba(16,185,129,0.15)' : 'rgba(37,99,235,0.15)') : 'rgba(255,255,255,0.04)',
                  border: sel ? `2px solid ${p.highlight ? 'rgba(16,185,129,0.5)' : 'rgba(37,99,235,0.5)'}` : '2px solid rgba(255,255,255,0.08)',
                  borderRadius: '12px', padding: '20px 12px', cursor: 'pointer', textAlign: 'center' as const,
                  transition: 'all 0.2s', position: 'relative',
                }}>
                  {p.highlight && (
                    <div style={{ position: 'absolute', top: '-8px', left: '50%', transform: 'translateX(-50%)', background: '#10b981', color: '#fff', fontSize: '10px', fontWeight: 800, padding: '2px 10px', borderRadius: '10px', whiteSpace: 'nowrap' as const }}>
                      BEST VALUE
                    </div>
                  )}
                  <Icon size={28} style={{ color: sel ? (p.highlight ? '#34d399' : '#60a5fa') : '#64748b', marginBottom: '8px' }} />
                  <div style={{ color: '#fff', fontSize: '15px', fontWeight: 700 }}>{p.label}</div>
                  <div style={{ color: '#64748b', fontSize: '12px', marginTop: '2px' }}>{p.desc}</div>
                  {sel && <CheckCircle size={16} style={{ position: 'absolute', top: '8px', right: '8px', color: p.highlight ? '#34d399' : '#60a5fa' }} />}
                </button>
              );
            })}
          </div>
        </div>
      )}

      {/* ── Contact ── */}
      {currentStepType === 'contact' && (
        <div>
          <h3 style={{ color: '#fff', fontSize: '20px', fontWeight: 700, margin: '0 0 4px' }}>Tell us about yourself</h3>
          <p style={{ color: '#94a3b8', fontSize: '14px', margin: '0 0 24px' }}>We need a few details to get your quotes.</p>
          <div style={{ display: 'flex', gap: '12px', marginBottom: '16px' }}>
            <div style={{ flex: 1 }}>
              <label style={lS}>First Name <span style={{ color: '#f87171' }}>*</span></label>
              <input style={iS} value={form.firstName} placeholder="John" onChange={e => setForm(p => ({ ...p, firstName: e.target.value }))} />
            </div>
            <div style={{ flex: 1 }}>
              <label style={lS}>Last Name</label>
              <input style={iS} value={form.lastName} placeholder="Smith" onChange={e => setForm(p => ({ ...p, lastName: e.target.value }))} />
            </div>
          </div>
          <div style={{ marginBottom: '16px' }}>
            <label style={lS}>Phone <span style={{ color: '#f87171' }}>*</span></label>
            <input style={iS} type="tel" value={form.phone} placeholder="(555) 123-4567" onChange={e => setForm(p => ({ ...p, phone: e.target.value }))} />
          </div>
          <div style={{ marginBottom: '16px' }}>
            <label style={lS}>Email</label>
            <input style={iS} type="email" value={form.email} placeholder="john@example.com" onChange={e => setForm(p => ({ ...p, email: e.target.value }))} />
          </div>
          <div>
            <label style={lS}>Date of Birth</label>
            <input style={iS} type="date" value={form.dob} onChange={e => setForm(p => ({ ...p, dob: e.target.value }))} />
          </div>
        </div>
      )}

      {/* ── Address ── */}
      {currentStepType === 'address' && (
        <div>
          <h3 style={{ color: '#fff', fontSize: '20px', fontWeight: 700, margin: '0 0 4px' }}>
            {needsHome ? 'Where is the property?' : 'What is your address?'}
          </h3>
          <p style={{ color: '#94a3b8', fontSize: '14px', margin: '0 0 24px' }}>This helps us find the most accurate rates for your area.</p>
          <div style={{ marginBottom: '16px' }}>
            <label style={lS}>Street Address <span style={{ color: '#f87171' }}>*</span></label>
            <input style={iS} value={form.address} placeholder="123 Main Street"
              autoComplete="address-line1" name="street-address"
              onChange={e => setForm(p => ({ ...p, address: e.target.value }))} />
          </div>
          <div style={{ display: 'flex', gap: '12px', marginBottom: '16px' }}>
            <div style={{ flex: 2 }}>
              <label style={lS}>City <span style={{ color: '#f87171' }}>*</span></label>
              <input style={iS} value={form.city} placeholder="Chicago"
                autoComplete="address-level2" name="city"
                onChange={e => setForm(p => ({ ...p, city: e.target.value }))} />
            </div>
            <div style={{ flex: 1 }}>
              <label style={lS}>State <span style={{ color: '#f87171' }}>*</span></label>
              <select style={selS} value={form.state} onChange={e => setForm(p => ({ ...p, state: e.target.value }))}>
                <option value="" style={optS}>--</option>
                {STATES.map(s => <option key={s} value={s} style={optS}>{s}</option>)}
              </select>
            </div>
            <div style={{ flex: 1 }}>
              <label style={lS}>ZIP <span style={{ color: '#f87171' }}>*</span></label>
              <input style={iS} value={form.zip} placeholder="60601" maxLength={5}
                autoComplete="postal-code" name="postal-code"
                onChange={e => setForm(p => ({ ...p, zip: e.target.value }))} />
            </div>
          </div>
        </div>
      )}

      {/* ── Property Details ── */}
      {currentStepType === 'property' && (
        <div>
          <h3 style={{ color: '#fff', fontSize: '20px', fontWeight: 700, margin: '0 0 4px' }}>Property Details</h3>
          <p style={{ color: '#94a3b8', fontSize: '14px', margin: '0 0 24px' }}>These help us find the most competitive rates. Skip any you don&apos;t know.</p>

          {/* Roof savings highlight - always visible */}
          <div style={{
            background: 'linear-gradient(135deg, rgba(16,185,129,0.1) 0%, rgba(37,99,235,0.08) 100%)',
            border: '1px solid rgba(16,185,129,0.25)',
            borderRadius: '12px', padding: '14px 18px', marginBottom: '20px',
            display: 'flex', alignItems: 'center', gap: '12px',
          }}>
            <span style={{ fontSize: '28px' }}>🏠</span>
            <div>
              <p style={{ color: '#34d399', fontSize: '15px', fontWeight: 700, margin: '0 0 2px' }}>
                Newer roof? You could save 15-30% on your premium!
              </p>
              <p style={{ color: '#94a3b8', fontSize: '13px', margin: 0 }}>
                Homes with roofs under 10 years old qualify for significant discounts with most carriers. Enter your roof year below to see your savings potential.
              </p>
            </div>
          </div>

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

          {/* Roof age info removed — agents handle this */}

          <div style={{ marginBottom: '16px' }}>
            <label style={lS}>Square Footage (approx.)</label>
            <input style={iS} value={form.sqft} placeholder="e.g. 2,200"
              onChange={e => setForm(p => ({ ...p, sqft: e.target.value }))} />
          </div>
          <p style={{ color: '#64748b', fontSize: '12px', margin: '8px 0 0', fontStyle: 'italic' }}>
            Don&apos;t worry if you don&apos;t have all of these — our agent can look them up.
          </p>
        </div>
      )}

      {/* ── Drivers ── */}
      {currentStepType === 'drivers' && (
        <div>
          <h3 style={{ color: '#fff', fontSize: '20px', fontWeight: 700, margin: '0 0 4px' }}>Drivers in the Household</h3>
          <p style={{ color: '#94a3b8', fontSize: '14px', margin: '0 0 24px' }}>List all licensed drivers for the most accurate auto rates.</p>
          {form.drivers.map((driver, idx) => (
            <div key={idx} style={{
              background: 'rgba(255,255,255,0.04)', borderRadius: '12px', padding: '16px',
              border: '1px solid rgba(255,255,255,0.08)', marginBottom: '12px', position: 'relative',
            }}>
              {idx > 0 && (
                <button onClick={() => removeDriver(idx)} style={{ position: 'absolute', top: '8px', right: '8px', background: 'none', border: 'none', color: '#64748b', cursor: 'pointer', padding: '4px' }}>
                  <X size={16} />
                </button>
              )}
              <div style={{ fontSize: '12px', color: '#64748b', fontWeight: 700, marginBottom: '10px', textTransform: 'uppercase' as const, letterSpacing: '0.5px' }}>
                {idx === 0 ? 'Primary Driver (You)' : `Driver ${idx + 1}`}
              </div>
              <div style={{ display: 'flex', gap: '12px', flexWrap: 'wrap' as const }}>
                <div style={{ flex: '2 1 180px' }}>
                  <label style={lS}>Full Name</label>
                  <input style={{ ...iS, ...(idx === 0 ? { color: '#94a3b8' } : {}) }} value={driver.name}
                    readOnly={idx === 0}
                    placeholder={idx === 0 ? 'Auto-filled from your info' : 'Driver name'}
                    onChange={e => idx > 0 && updateDriver(idx, 'name', e.target.value)} />
                </div>
                <div style={{ flex: '1 1 140px' }}>
                  <label style={lS}>Date of Birth</label>
                  <input style={{ ...iS, ...(idx === 0 ? { color: '#94a3b8' } : {}) }} type="date" value={driver.dob}
                    readOnly={idx === 0}
                    onChange={e => idx > 0 && updateDriver(idx, 'dob', e.target.value)} />
                </div>
                {idx > 0 && (
                  <div style={{ flex: '1 1 140px' }}>
                    <label style={lS}>Relationship</label>
                    <select style={selS} value={driver.relationship} onChange={e => updateDriver(idx, 'relationship', e.target.value)}>
                      <option value="" style={optS}>Select...</option>
                      <option value="Spouse" style={optS}>Spouse</option>
                      <option value="Child" style={optS}>Child</option>
                      <option value="Parent" style={optS}>Parent</option>
                      <option value="Other" style={optS}>Other</option>
                    </select>
                  </div>
                )}
              </div>
              {idx === 0 && <p style={{ color: '#475569', fontSize: '11px', margin: '8px 0 0', fontStyle: 'italic' }}>Pre-filled from your contact info</p>}
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

      {/* ── Vehicles ── */}
      {currentStepType === 'vehicles' && (
        <div>
          <h3 style={{ color: '#fff', fontSize: '20px', fontWeight: 700, margin: '0 0 4px' }}>Vehicles in the Household</h3>
          <p style={{ color: '#94a3b8', fontSize: '14px', margin: '0 0 24px' }}>List all vehicles you&apos;d like quoted. We&apos;ll find the best rate for each.</p>
          {form.vehicles.map((vehicle, idx) => (
            <div key={idx} style={{
              background: 'rgba(255,255,255,0.04)', borderRadius: '12px', padding: '16px',
              border: '1px solid rgba(255,255,255,0.08)', marginBottom: '12px', position: 'relative',
            }}>
              {idx > 0 && (
                <button onClick={() => removeVehicle(idx)} style={{ position: 'absolute', top: '8px', right: '8px', background: 'none', border: 'none', color: '#64748b', cursor: 'pointer', padding: '4px' }}>
                  <X size={16} />
                </button>
              )}
              <div style={{ fontSize: '12px', color: '#64748b', fontWeight: 700, marginBottom: '10px', textTransform: 'uppercase' as const, letterSpacing: '0.5px' }}>
                Vehicle {idx + 1}
              </div>
              <div style={{ display: 'flex', gap: '12px', flexWrap: 'wrap' as const }}>
                <div style={{ flex: '1 1 80px' }}>
                  <label style={lS}>Year</label>
                  <input style={iS} value={vehicle.year} placeholder="e.g. 2021" maxLength={4}
                    onChange={e => updateVehicle(idx, 'year', e.target.value)} />
                </div>
                <div style={{ flex: '2 1 120px' }}>
                  <label style={lS}>Make</label>
                  <input style={iS} value={vehicle.make} placeholder="e.g. Toyota"
                    onChange={e => updateVehicle(idx, 'make', e.target.value)} />
                </div>
                <div style={{ flex: '2 1 120px' }}>
                  <label style={lS}>Model</label>
                  <input style={iS} value={vehicle.model} placeholder="e.g. Camry"
                    onChange={e => updateVehicle(idx, 'model', e.target.value)} />
                </div>
              </div>
            </div>
          ))}
          <button onClick={addVehicle} style={{
            display: 'flex', alignItems: 'center', gap: '6px', background: 'none',
            border: '1px dashed rgba(255,255,255,0.15)', borderRadius: '8px', padding: '10px 16px',
            color: '#60a5fa', fontSize: '14px', fontWeight: 600, cursor: 'pointer', width: '100%', justifyContent: 'center',
          }}>
            <Plus size={16} /> Add Another Vehicle
          </button>
        </div>
      )}

      {/* ── Current Coverage ── */}
      {currentStepType === 'coverage' && (
        <div>
          <h3 style={{ color: '#fff', fontSize: '20px', fontWeight: 700, margin: '0 0 4px' }}>Almost done!</h3>
          <p style={{ color: '#94a3b8', fontSize: '14px', margin: '0 0 24px' }}>This helps us understand what to beat. Both fields are optional.</p>
          <div style={{ marginBottom: '16px' }}>
            <label style={lS}>Current Insurance Carrier</label>
            <select style={selS} value={form.currentCarrier} onChange={e => setForm(p => ({ ...p, currentCarrier: e.target.value }))}>
              <option value="" style={optS}>Select your carrier...</option>
              {CARRIERS.map(c => <option key={c} value={c} style={optS}>{c}</option>)}
            </select>
          </div>
          <div style={{ marginBottom: '24px' }}>
            <label style={lS}>Current Annual Premium (approx.)</label>
            <div style={{ position: 'relative' }}>
              <span style={{ position: 'absolute', left: '16px', top: '50%', transform: 'translateY(-50%)', color: '#64748b' }}>$</span>
              <input style={{ ...iS, paddingLeft: '28px' }} value={form.currentPremium} placeholder="e.g. 2,400"
                onChange={e => setForm(p => ({ ...p, currentPremium: e.target.value }))} />
            </div>
          </div>
          <div style={{ background: 'rgba(255,255,255,0.04)', borderRadius: '12px', padding: '16px', border: '1px solid rgba(255,255,255,0.08)', marginBottom: '20px' }}>
            <div style={{ display: 'flex', gap: '12px', alignItems: 'flex-start' }}>
              <input type="checkbox" checked={form.privacyConsent}
                onChange={e => setForm(p => ({ ...p, privacyConsent: e.target.checked }))}
                style={{ marginTop: '4px', accentColor: '#2563eb', width: '18px', height: '18px', flexShrink: 0 }} />
              <p style={{ color: '#e2e8f0', fontSize: '13px', lineHeight: 1.6, margin: 0 }}>
                I consent to Better Choice Insurance Group collecting and using the information provided to obtain insurance quotes on my behalf from their carrier partners. I understand my information may be shared with insurance carriers for the purpose of generating quotes, and that I may be contacted by phone, email, or text regarding my quote request.{' '}
                <a href="/privacy" target="_blank" style={{ color: '#60a5fa', textDecoration: 'underline' }}>Privacy Policy</a>
              </p>
            </div>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: '#64748b', fontSize: '12px', marginBottom: '16px' }}>
            <Lock size={14} /> Your information is encrypted and never sold to third parties.
          </div>
        </div>
      )}

      {/* ── Nav buttons ── */}
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
