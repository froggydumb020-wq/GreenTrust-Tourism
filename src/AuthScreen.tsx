import { FormEvent, useState } from 'react';
import {
  AlertCircle,
  ArrowLeft,
  Building2,
  Eye,
  EyeOff,
  Loader2,
  Lock,
  LogIn,
  Mail,
  MapPin,
  Phone,
  User,
  UserPlus,
} from 'lucide-react';
import {
  loginHotel,
  registerHotel,
  type Hotel,
} from '@/api';

type Mode = 'login' | 'register';

const HOTEL_TYPES = [
  'Resort', 'Hotel', 'Boutique Hotel', 'Homestay', 'Villa',
  'Lodge', 'Guest House', 'Hostel', 'Serviced Apartment', 'Eco Lodge',
];

const FIELD_LABELS: Record<string, string> = {
  hotel_name: 'Hotel Name',
  registration_number: 'License / Registration No.',
  hotel_type: 'Hotel Type',
  number_of_rooms: 'Number of Rooms',
  street_address: 'Street Address',
  city: 'City',
  state: 'State',
  pin_zip: 'PIN / ZIP',
  country: 'Country',
  contact_person: 'Contact Person',
  phone: 'Phone',
  email: 'Official Email',
  password: 'Password',
  confirm_password: 'Confirm Password',
};

type Props = {
  mode: Mode;
  onAuthed: (hotel: Hotel) => void;
  onSwitchMode: (mode: Mode) => void;
};

export default function AuthScreen({ mode, onAuthed, onSwitchMode }: Props) {
  const [form, setForm] = useState<Record<string, string>>({});
  const [showPassword, setShowPassword] = useState(false);
  const [showConfirm, setShowConfirm] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const set = (key: string, value: string) => setForm((cur) => ({ ...cur, [key]: value }));

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      if (mode === 'register') {
        if (form.password !== form.confirm_password) {
          setError('Passwords do not match');
          setLoading(false);
          return;
        }
        const { hotel } = await registerHotel(form);
        onAuthed(hotel);
      } else {
        const { hotel } = await loginHotel(form.email || '', form.password || '');
        onAuthed(hotel);
      }
    } catch (err: any) {
      const msg = err?.message || 'Authentication failed';
      setError(msg.replace(/^API \d+: ?/, ''));
    } finally {
      setLoading(false);
    }
  };

  const isRegister = mode === 'register';

  return (
    <div className="auth-shell">
      <div className="auth-bg" style={{ backgroundImage: `url('/${isRegister ? 'registerpage' : 'loginpage'}.png')` }} />
      <div className="auth-overlay" />

      <div className="auth-card-wrap">
        <div className="auth-card">
          <a className="auth-home-link" href="/">
            <ArrowLeft size={15} /> Back to Home
          </a>
          <div className="auth-brand">
            <div className="auth-logo">
              <img src="/ChatGPT_Image_Sep_26,_2026,_08_43_25_PM.png" alt="GreenTrust" />
            </div>
            <div className="auth-brand-text">
              <strong>GreenTrust</strong>
              <span>SUSTAINABLE TOURISM</span>
            </div>
          </div>

          <div className="auth-head">
            <h1>{isRegister ? 'Register your hotel' : 'Welcome back'}</h1>
            <p>{isRegister ? 'Create your GreenTrust workspace to begin evidence verification.' : 'Sign in to your GreenTrust workspace to continue.'}</p>
          </div>

          {error && (
            <div className="auth-error">
              <AlertCircle size={15} />
              <span>{error}</span>
            </div>
          )}

          <form className="auth-form" onSubmit={submit}>
            {isRegister ? (
              <>
                <div className="auth-grid">
                  <AuthField icon={Building2} label={FIELD_LABELS.hotel_name} value={form.hotel_name || ''} onChange={(v) => set('hotel_name', v)} required type="text" autoComplete="organization" />
                  <AuthField icon={Lock} label={FIELD_LABELS.registration_number} value={form.registration_number || ''} onChange={(v) => set('registration_number', v)} required type="text" />
                </div>
                <div className="auth-grid">
                  <AuthSelect icon={Building2} label={FIELD_LABELS.hotel_type} value={form.hotel_type || ''} onChange={(v) => set('hotel_type', v)} options={HOTEL_TYPES} />
                  <AuthField icon={Building2} label={FIELD_LABELS.number_of_rooms} value={form.number_of_rooms || ''} onChange={(v) => set('number_of_rooms', v)} type="number" min="0" />
                </div>
                <AuthField icon={MapPin} label={FIELD_LABELS.street_address} value={form.street_address || ''} onChange={(v) => set('street_address', v)} required type="text" autoComplete="address-line1" />
                <div className="auth-grid">
                  <AuthField icon={MapPin} label={FIELD_LABELS.city} value={form.city || ''} onChange={(v) => set('city', v)} required type="text" autoComplete="address-level2" />
                  <AuthField icon={MapPin} label={FIELD_LABELS.state} value={form.state || ''} onChange={(v) => set('state', v)} required type="text" autoComplete="address-level1" />
                </div>
                <div className="auth-grid">
                  <AuthField icon={MapPin} label={FIELD_LABELS.pin_zip} value={form.pin_zip || ''} onChange={(v) => set('pin_zip', v)} required type="text" autoComplete="postal-code" />
                  <AuthField icon={MapPin} label={FIELD_LABELS.country} value={form.country || ''} onChange={(v) => set('country', v)} required type="text" autoComplete="country-name" />
                </div>
                <div className="auth-grid">
                  <AuthField icon={User} label={FIELD_LABELS.contact_person} value={form.contact_person || ''} onChange={(v) => set('contact_person', v)} required type="text" autoComplete="name" />
                  <AuthField icon={Phone} label={FIELD_LABELS.phone} value={form.phone || ''} onChange={(v) => set('phone', v)} required type="tel" autoComplete="tel" />
                </div>
                <AuthField icon={Mail} label={FIELD_LABELS.email} value={form.email || ''} onChange={(v) => set('email', v)} required type="email" autoComplete="email" />
                <div className="auth-grid">
                  <PasswordField icon={Lock} label={FIELD_LABELS.password} value={form.password || ''} onChange={(v) => set('password', v)} required show={showPassword} onToggle={() => setShowPassword((s) => !s)} />
                  <PasswordField icon={Lock} label={FIELD_LABELS.confirm_password} value={form.confirm_password || ''} onChange={(v) => set('confirm_password', v)} required show={showConfirm} onToggle={() => setShowConfirm((s) => !s)} />
                </div>
              </>
            ) : (
              <>
                <AuthField icon={Mail} label={FIELD_LABELS.email} value={form.email || ''} onChange={(v) => set('email', v)} required type="email" autoComplete="email" />
                <PasswordField icon={Lock} label={FIELD_LABELS.password} value={form.password || ''} onChange={(v) => set('password', v)} required show={showPassword} onToggle={() => setShowPassword((s) => !s)} />
                <div className="auth-row-between">
                  <label className="auth-remember">
                    <input type="checkbox" /> <span>Keep me signed in</span>
                  </label>
                  <button type="button" className="auth-link" onClick={() => setError('Password reset is not enabled in Phase 1.')}>Forgot password?</button>
                </div>
              </>
            )}

            <button type="submit" className="auth-submit" disabled={loading}>
              {loading ? <Loader2 className="spin" size={17} /> : isRegister ? <UserPlus size={17} /> : <LogIn size={17} />}
              <span>{isRegister ? 'Create hotel account' : 'Sign in'}</span>
            </button>

            {!isRegister && (
              <button type="button" className="auth-google" disabled={loading}>
                <GoogleIcon />
                <span>Sign in with Google</span>
              </button>
            )}

            <p className="auth-switch">
              {isRegister ? 'Already have an account?' : "Don't have an account?"}{' '}
              <button type="button" className="auth-link" onClick={() => { setError(null); onSwitchMode(isRegister ? 'login' : 'register'); }}>
                {isRegister ? 'Sign in' : 'Register your hotel'}
              </button>
            </p>
          </form>
        </div>
      </div>
    </div>
  );
}

function AuthField({ icon: Icon, label, value, onChange, required, type = 'text', autoComplete, min }: {
  icon: typeof Mail; label: string; value: string; onChange: (v: string) => void; required?: boolean; type?: string; autoComplete?: string; min?: string;
}) {
  return (
    <label className="auth-field">
      <span>{label}{required && <i>*</i>}</span>
      <div className="auth-input">
        <Icon size={16} />
        <input type={type} value={value} onChange={(e) => onChange(e.target.value)} required={required} autoComplete={autoComplete} min={min} placeholder={label} />
      </div>
    </label>
  );
}

function AuthSelect({ icon: Icon, label, value, onChange, options }: {
  icon: typeof Mail; label: string; value: string; onChange: (v: string) => void; options: string[];
}) {
  return (
    <label className="auth-field">
      <span>{label}</span>
      <div className="auth-input">
        <Icon size={16} />
        <select value={value} onChange={(e) => onChange(e.target.value)}>
          <option value="">Select type</option>
          {options.map((o) => <option key={o} value={o}>{o}</option>)}
        </select>
      </div>
    </label>
  );
}

function PasswordField({ icon: Icon, label, value, onChange, required, show, onToggle }: {
  icon: typeof Mail; label: string; value: string; onChange: (v: string) => void; required?: boolean; show: boolean; onToggle: () => void;
}) {
  return (
    <label className="auth-field">
      <span>{label}{required && <i>*</i>}</span>
      <div className="auth-input">
        <Icon size={16} />
        <input type={show ? 'text' : 'password'} value={value} onChange={(e) => onChange(e.target.value)} required={required} autoComplete={label.includes('Confirm') ? 'new-password' : 'current-password'} placeholder={label} />
        <button type="button" className="auth-eye" onClick={onToggle} aria-label={show ? 'Hide password' : 'Show password'}>
          {show ? <EyeOff size={16} /> : <Eye size={16} />}
        </button>
      </div>
    </label>
  );
}

function GoogleIcon() {
  return (
    <svg width="17" height="17" viewBox="0 0 24 24" aria-hidden="true">
      <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 0 1-2.2 3.32v2.76h3.56c2.08-1.92 3.28-4.74 3.28-8.09z" />
      <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.56-2.76c-.98.66-2.23 1.06-3.72 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84A11 11 0 0 0 12 23z" />
      <path fill="#FBBC05" d="M5.84 14.11A6.6 6.6 0 0 1 5.48 12c0-.74.13-1.45.36-2.11V7.05H2.18A11 11 0 0 0 1 12c0 1.78.43 3.46 1.18 4.95l3.66-2.84z" />
      <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.05l3.66 2.84C6.71 7.31 9.14 5.38 12 5.38z" />
    </svg>
  );
}
