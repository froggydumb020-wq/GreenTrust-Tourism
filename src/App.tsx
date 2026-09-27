import { ChangeEvent, DragEvent, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  AlertCircle,
  Banknote,
  Bell,
  Calendar,
  CheckCircle2,
  ChevronRight,
  Clock3,
  CloudUpload,
  FileCheck2,
  FileText,
  FolderOpen,
  Gauge,
  Leaf,
  ListChecks,
  Loader2,
  LogOut,
  Menu,
  MoreHorizontal,
  Plus,
  Ruler,
  Search,
  Settings2,
  ShieldCheck,
  Sparkles,
  Tag,
  Upload,
  X,
  XCircle,
} from 'lucide-react';
import {
  PACKAGE_TYPES,
  computePackageStats,
  type DocumentItem,
  type DocStatus,
  type Hotel,
  type PackageInfo,
  type View,
  checkBackend,
  clearSession,
  fetchDocuments,
  fetchDocumentDetail,
  fetchMe,
  uploadDocument,
  getMockDocuments,
  createMockUpload,
  mockComplete,
} from '@/api';
import AuthScreen from '@/AuthScreen';

function initials(name: string): string {
  const parts = (name || '').trim().split(/\s+/);
  if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase();
  return (parts[0] || 'HT').slice(0, 2).toUpperCase();
}

const packageMeta: Record<string, { description: string; icon: typeof ShieldCheck; color: string }> = {
  'Sustainability & Legal': { description: 'Policies, licenses, and sustainability commitments', icon: ShieldCheck, color: 'forest' },
  'Energy & Water': { description: 'Utility statements and resource consumption', icon: Gauge, color: 'teal' },
  'Waste Management': { description: 'Collection records and waste reduction plans', icon: Leaf, color: 'amber' },
  'Environmental Practices': { description: 'Biodiversity and conservation evidence', icon: Sparkles, color: 'sky' },
};

const navItems: { label: string; view: View; icon: typeof Gauge }[] = [
  { label: 'Dashboard', view: 'dashboard', icon: Gauge },
  { label: 'Evidence Packages', view: 'packages', icon: FolderOpen },
  { label: 'Upload Document', view: 'upload', icon: CloudUpload },
  { label: 'My Documents', view: 'documents', icon: FileText },
];

function App() {
  const [view, setView] = useState<View>('dashboard');
  const [documents, setDocuments] = useState<DocumentItem[]>(getMockDocuments());
  const [selectedDocument, setSelectedDocument] = useState<DocumentItem | null>(null);
  const [isMobileNavOpen, setMobileNavOpen] = useState(false);
  const [isDragging, setDragging] = useState(false);
  const [search, setSearch] = useState('');
  const [backendOnline, setBackendOnline] = useState(false);
  const [loading, setLoading] = useState(true);
  const [uploadingPackage, setUploadingPackage] = useState<string>(PACKAGE_TYPES[1]);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [hotel, setHotel] = useState<Hotel | null>(null);
  const [authMode, setAuthMode] = useState<'login' | 'register'>('login');
  const [booting, setBooting] = useState(true);
  const hotelRef = useRef<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setBooting(true);
      const online = await checkBackend();
      if (cancelled) return;
      setBackendOnline(online);
      if (online) {
        const me = await fetchMe();
        if (cancelled) return;
        if (me) {
          setHotel(me);
          hotelRef.current = me._id;
          try {
            const docs = await fetchDocuments(me._id);
            if (cancelled) return;
            if (docs.length > 0) setDocuments(docs);
          } catch { /* keep mock if fetch fails */
          }
        }
      }
      setBooting(false);
      setLoading(false);
    })();
    return () => { cancelled = true; };
  }, []);

  const handleAuthed = useCallback((h: Hotel) => {
    setHotel(h);
    hotelRef.current = h._id;
    setView('dashboard');
    setDocuments(getMockDocuments());
    setLoading(false);
  }, []);

  const handleLogout = useCallback(() => {
    clearSession();
    setHotel(null);
    hotelRef.current = null;
    setDocuments(getMockDocuments());
    setView('dashboard');
    setAuthMode('login');
  }, []);

  const refreshDocuments = useCallback(async () => {
    if (!hotelRef.current) return;
    try {
      const docs = await fetchDocuments(hotelRef.current);
      setDocuments(docs);
    } catch { /* ignore */
    }
  }, []);

  useEffect(() => {
    if (!backendOnline) return;
    const hasProcessing = documents.some((d) => d.status === 'Processing');
    if (!hasProcessing) return;
    const interval = setInterval(refreshDocuments, 3000);
    return () => clearInterval(interval);
  }, [backendOnline, documents, refreshDocuments]);

  const packageStats = useMemo(() => computePackageStats(documents), [documents]);

  const filteredDocuments = useMemo(
    () => documents.filter((d) => d.name.toLowerCase().includes(search.toLowerCase()) || d.package.toLowerCase().includes(search.toLowerCase())),
    [documents, search],
  );

  const handleFiles = useCallback(async (files: FileList | null) => {
    if (!files?.length) return;
    const file = files[0];
    setUploadError(null);
    setUploading(true);

    if (!backendOnline || !hotelRef.current) {
      const mock = createMockUpload(file, uploadingPackage);
      setDocuments((cur) => [mock, ...cur]);
      setView('documents');
      setUploading(false);
      window.setTimeout(() => {
        setDocuments((cur) => cur.map((item) => (item.id === mock.id ? mockComplete(item) : item)));
      }, 1800);
      return;
    }

    try {
      const newDoc = await uploadDocument(file, hotelRef.current!, uploadingPackage);
      setDocuments((cur) => [newDoc, ...cur]);
      setView('documents');
    } catch (err: any) {
      setUploadError(err.message || 'Upload failed. Please try again.');
    } finally {
      setUploading(false);
    }
  }, [backendOnline, uploadingPackage]);

  const onDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setDragging(false);
    handleFiles(event.dataTransfer.files);
  };

  const openDocument = useCallback(async (document: DocumentItem) => {
    setSelectedDocument(document);
    if (backendOnline && document.status === 'Processed' && !document.extractedText) {
      try {
        const detail = await fetchDocumentDetail(document.id);
        setSelectedDocument(detail);
      } catch { /* keep existing */
      }
    }
  }, [backendOnline]);

  if (booting) {
    return <div className="loading-state" style={{ minHeight: '100vh' }}><Loader2 className="spin" size={28} /><p>Loading GreenTrust...</p></div>;
  }

  if (!hotel) {
    return <AuthScreen mode={authMode} onAuthed={handleAuthed} onSwitchMode={setAuthMode} />;
  }

  const hotelName = hotel.hotel_name || 'Hotel';
  const hotelInitials = initials(hotelName);

  return (
    <div className="app-shell">
      <aside className={`sidebar ${isMobileNavOpen ? 'sidebar-open' : ''}`}>
        <div className="brand-lockup">
          <div className="brand-mark"><img src="/ChatGPT_Image_Sep_26,_2026,_08_43_25_PM.png" alt="GreenTrust" /></div>
          <div><strong>GreenTrust</strong><span>SUSTAINABLE TOURISM</span></div>
          <button className="icon-button mobile-close" onClick={() => setMobileNavOpen(false)} aria-label="Close navigation"><X size={18} /></button>
        </div>
        <div className="workspace-label">WORKSPACE</div>
        <nav className="main-nav">
          {navItems.map(({ label, view: navView, icon: Icon }) => <button key={navView} className={view === navView ? 'nav-item active' : 'nav-item'} onClick={() => { setView(navView); setMobileNavOpen(false); }}><Icon size={19} /><span>{label}</span>{navView === 'upload' && <span className="nav-badge">+</span>}</button>)}
        </nav>
        <div className="sidebar-spacer" />
        <div className="sidebar-note"><Leaf size={17} /><p><strong>Phase 1</strong><br />Evidence ingestion<br />& preprocessing</p></div>
        <button className={view === 'profile' ? 'nav-item active' : 'nav-item'} onClick={() => setView('profile')}><Settings2 size={19} /><span>Profile & settings</span></button>
        <button className="nav-item" onClick={handleLogout}><LogOut size={19} /><span>Sign out</span></button>
        <div className="account-chip"><div className="avatar">{hotelInitials}</div><div><strong>{hotelName}</strong><span>Hotel workspace</span></div><MoreHorizontal size={18} /></div>
      </aside>

      <main className="main-content">
        <header className="topbar">
          <button className="icon-button menu-trigger" onClick={() => setMobileNavOpen(true)} aria-label="Open navigation"><Menu size={21} /></button>
          <div className="breadcrumb"><span>{hotelName}</span><ChevronRight size={14} /><strong>{view === 'dashboard' ? 'Dashboard' : view === 'packages' ? 'Evidence Packages' : view === 'upload' ? 'Upload Document' : view === 'documents' ? 'My Documents' : 'Profile'}</strong></div>
          <div className="topbar-actions">
            <div className={`connection-badge ${backendOnline ? 'online' : 'offline'}`}>
              <i />{backendOnline ? 'Live' : 'Demo'}
            </div>
            <label className="search-box"><Search size={17} /><input value={search} onChange={(event: ChangeEvent<HTMLInputElement>) => setSearch(event.target.value)} placeholder="Search documents" /></label>
            <button className="notification-button" aria-label="Notifications"><Bell size={19} /><i /></button>
            <div className="top-avatar">{hotelInitials}</div>
          </div>
        </header>

        <div className="page-content">
          {loading ? (
            <div className="loading-state"><Loader2 className="spin" size={28} /><p>Connecting to GreenTrust backend...</p></div>
          ) : (
            <>
              {view === 'dashboard' && <Dashboard documents={documents} packageStats={packageStats} onNavigate={setView} onOpen={openDocument} backendOnline={backendOnline} hotelName={hotelName} />}
              {view === 'packages' && <Packages packageStats={packageStats} onNavigate={setView} />}
              {view === 'upload' && <UploadView isDragging={isDragging} setDragging={setDragging} handleFiles={handleFiles} uploadingPackage={uploadingPackage} setUploadingPackage={setUploadingPackage} uploadError={uploadError} uploading={uploading} backendOnline={backendOnline} />}
              {view === 'documents' && <Documents documents={filteredDocuments} onOpen={openDocument} onNavigate={setView} />}
              {view === 'profile' && <Profile hotel={hotel} />}
            </>
          )}
        </div>
      </main>

      {selectedDocument && <DocumentDetails document={selectedDocument} onClose={() => setSelectedDocument(null)} />}
    </div>
  );
}

function Dashboard({ documents, packageStats, onNavigate, onOpen, backendOnline, hotelName }: { documents: DocumentItem[]; packageStats: PackageInfo[]; onNavigate: (view: View) => void; onOpen: (doc: DocumentItem) => void; backendOnline: boolean; hotelName: string }) {
  const processed = documents.filter((d) => d.status === 'Processed').length;
  const processing = documents.filter((d) => d.status === 'Processing').length;
  const failed = documents.filter((d) => d.status === 'Failed').length;
  const hour = new Date().getHours();
  const greeting = hour < 12 ? 'Good morning' : hour < 18 ? 'Good afternoon' : 'Good evening';
  return <>
    <section className="welcome-row"><div><p className="eyebrow">{new Date().toLocaleDateString([], { weekday: 'long', month: 'long', day: 'numeric', year: 'numeric' })}</p><h1>{greeting}, {hotelName}.</h1><p className="subheading">{backendOnline ? 'Connected to live backend. Your data is synced.' : 'Running in demo mode. Start the backend to use the full pipeline.'}</p></div><button className="primary-button" onClick={() => onNavigate('upload')}><Plus size={18} /> Upload evidence</button></section>
    <section className="stat-grid"><StatCard label="Total documents" value={documents.length} detail="Across all packages" icon={FileText} tone="green" /><StatCard label="Processed" value={processed} detail="Ready for review" icon={CheckCircle2} tone="teal" /><StatCard label="Processing" value={processing} detail="Usually under 2 min" icon={Clock3} tone="amber" /><StatCard label="Failed" value={failed} detail="Needs your attention" icon={XCircle} tone="red" /></section>
    <section className="section-heading"><div><p className="eyebrow">YOUR WORKSPACE</p><h2>Evidence packages</h2></div><button className="text-button" onClick={() => onNavigate('packages')}>View all packages <ChevronRight size={16} /></button></section>
    <div className="package-grid">{packageStats.map((item) => <PackageCard key={item.name} item={item} onClick={() => onNavigate('packages')} />)}</div>
    <section className="section-heading latest-heading"><div><p className="eyebrow">RECENT ACTIVITY</p><h2>Latest documents</h2></div><button className="text-button" onClick={() => onNavigate('documents')}>View all documents <ChevronRight size={16} /></button></section>
    <DocumentTable documents={documents.slice(0, 5)} onOpen={onOpen} />
  </>;
}

function StatCard({ label, value, detail, icon: Icon, tone }: { label: string; value: number; detail: string; icon: typeof FileText; tone: string }) { return <div className="stat-card"><div className={`stat-icon ${tone}`}><Icon size={19} /></div><div><span>{label}</span><strong>{value}</strong><small>{detail}</small></div></div>; }

function PackageCard({ item, onClick }: { item: PackageInfo; onClick: () => void }) {
  const meta = packageMeta[item.name] || packageMeta['Sustainability & Legal'];
  const Icon = meta.icon;
  return <button className="package-card" onClick={onClick}><div className={`package-icon ${meta.color}`}><Icon size={20} /></div><div className="package-card-copy"><div className="package-title"><strong>{item.name}</strong><span>{item.count} docs</span></div><p>{meta.description}</p><div className="progress-label"><span>Completion</span><b>{item.progress}%</b></div><div className="progress-track"><i style={{ width: `${item.progress}%` }} /></div></div><ChevronRight className="package-arrow" size={18} /></button>;
}

function Documents({ documents, onOpen, onNavigate }: { documents: DocumentItem[]; onOpen: (doc: DocumentItem) => void; onNavigate: (view: View) => void }) { return <><section className="welcome-row compact"><div><p className="eyebrow">DOCUMENT LIBRARY</p><h1>My documents</h1><p className="subheading">Every uploaded file, parsed and organized in one place.</p></div><button className="primary-button" onClick={() => onNavigate('upload')}><Upload size={17} /> Upload document</button></section><DocumentTable documents={documents} onOpen={onOpen} /></>; }
function DocumentTable({ documents, onOpen }: { documents: DocumentItem[]; onOpen: (doc: DocumentItem) => void }) { return <div className="document-table"><div className="table-head"><span>Document</span><span>Package</span><span>Uploaded</span><span>Status</span><span /></div>{documents.map((doc) => <button className="document-row" key={doc.id} onClick={() => onOpen(doc)}><div className="document-name"><div className={`file-icon ${doc.type.toLowerCase()}`}>{doc.type === 'PDF' ? <FileText size={18} /> : <FileCheck2 size={18} />}</div><div><strong>{doc.name}</strong><span>{doc.type} · {doc.size}</span></div></div><span className="table-package">{doc.package}</span><span className="table-date">{doc.uploaded}</span><StatusPill status={doc.status} /><ChevronRight className="row-arrow" size={17} /></button>)}{documents.length === 0 && <div className="empty-state">No documents match that search.</div>}</div>; }
function StatusPill({ status }: { status: DocStatus }) { return <span className={`status-pill ${status.toLowerCase()}`}><i />{status}</span>; }

function Packages({ packageStats, onNavigate }: { packageStats: PackageInfo[]; onNavigate: (view: View) => void }) {
  return <><section className="welcome-row compact"><div><p className="eyebrow">ORGANIZE YOUR EVIDENCE</p><h1>Evidence packages</h1><p className="subheading">Keep related documents together and see what&apos;s ready to process.</p></div><button className="primary-button" onClick={() => onNavigate('upload')}><Plus size={18} /> Add evidence</button></section><div className="package-list">{packageStats.map((item) => <PackageCard key={item.name} item={item} onClick={() => onNavigate('upload')} />)}</div></>;
}

function UploadView({ isDragging, setDragging, handleFiles, uploadingPackage, setUploadingPackage, uploadError, uploading, backendOnline }: {
  isDragging: boolean; setDragging: (v: boolean) => void; handleFiles: (files: FileList | null) => void;
  uploadingPackage: string; setUploadingPackage: (v: string) => void; uploadError: string | null; uploading: boolean; backendOnline: boolean;
}) {
  return <><section className="welcome-row compact"><div><p className="eyebrow">NEW EVIDENCE</p><h1>Upload a document</h1><p className="subheading">{backendOnline ? 'Connected to live backend — your file will go through the full pipeline.' : 'Demo mode — upload will be simulated. Start the backend for real processing.'}</p></div></section>
    <div className="upload-layout">
      <div className="upload-card">
        <div className="upload-package-selector">
          <label>Evidence package</label>
          <select value={uploadingPackage} onChange={(e) => setUploadingPackage(e.target.value)}>
            {PACKAGE_TYPES.map((p) => <option key={p} value={p}>{p}</option>)}
          </select>
        </div>
        <div className={`drop-zone ${isDragging ? 'dragging' : ''}`} onDragOver={(e) => { e.preventDefault(); setDragging(true); }} onDragLeave={() => setDragging(false)} onDrop={(e) => { e.preventDefault(); setDragging(false); handleFiles(e.dataTransfer.files); }}>
          <div className="upload-orb">{uploading ? <Loader2 className="spin" size={28} /> : <CloudUpload size={28} />}</div>
          <h3>{uploading ? 'Uploading...' : 'Drop your document here'}</h3>
          <p>{uploading ? 'Please wait while your file is being uploaded' : 'or choose a file from your device'}</p>
          <label className="primary-button file-button"><Upload size={17} /> Choose file<input type="file" accept=".pdf,.docx,.png,.jpg,.jpeg" disabled={uploading} onChange={(e) => handleFiles(e.target.files)} /></label>
          <span>PDF, DOCX, PNG or JPG · Max 20 MB</span>
        </div>
        {uploadError && <div className="upload-error"><AlertCircle size={16} /> {uploadError}</div>}
      </div>
      <div className="upload-info"><div className="info-card"><div className="info-card-icon"><Sparkles size={19} /></div><div><strong>What happens next?</strong><p>GreenTrust validates your file, extracts its text, cleans up noise, and creates a searchable structured record.</p></div></div><div className="info-card"><div className="info-card-icon muted"><ShieldCheck size={19} /></div><div><strong>Your files stay organized</strong><p>Every document is linked to an evidence package and given a unique integrity hash.</p></div></div></div>
    </div>
  </>;
}

function Profile({ hotel }: { hotel: Hotel }) {
  const name = hotel.hotel_name || 'Hotel';
  const initialsVal = initials(name);
  const locationStr = [hotel.city, hotel.state, hotel.country].filter(Boolean).join(', ') || '—';
  return <><section className="welcome-row compact"><div><p className="eyebrow">WORKSPACE SETTINGS</p><h1>Profile</h1><p className="subheading">Manage your hotel workspace details.</p></div></section><div className="profile-card"><div className="profile-banner" /><div className="profile-body"><div className="profile-avatar">{initialsVal}</div><h2>{name}</h2><p>Hotel workspace · {locationStr}</p><div className="profile-fields"><div><span>Contact email</span><strong>{hotel.email || '—'}</strong></div><div><span>Registration number</span><strong>{hotel.registration_number || '—'}</strong></div><div><span>Contact person</span><strong>{hotel.contact_person || '—'}</strong></div><div><span>Phone</span><strong>{hotel.phone || '—'}</strong></div><div><span>Hotel type</span><strong>{hotel.hotel_type || '—'}</strong></div><div><span>Number of rooms</span><strong>{hotel.number_of_rooms ?? '—'}</strong></div><div><span>Street address</span><strong>{hotel.street_address || '—'}</strong></div><div><span>PIN / ZIP</span><strong>{hotel.pin_zip || '—'}</strong></div></div></div></div></>;
}

function DetailList({ icon: Icon, title, items }: { icon: typeof Tag; title: string; items: string[] }) {
  if (!items || items.length === 0) return null;
  return <div className="detail-section"><h3>{title}</h3><div className="tag-list">{items.map((item, i) => <span key={i} className="extracted-tag"><Icon size={11} /> {item}</span>)}</div></div>;
}

function KeyValueGrid({ fields }: { fields: Record<string, string> }) {
  const entries = Object.entries(fields);
  if (entries.length === 0) return null;
  return <div className="detail-section"><h3>Key-value fields</h3><div className="kv-grid">{entries.map(([key, value]) => <div key={key} className="kv-item"><span>{key.replace(/_/g, ' ')}</span><strong>{value}</strong></div>)}</div></div>;
}

function DocumentDetails({ document, onClose }: { document: DocumentItem; onClose: () => void }) {
  const structured = document.structuredData as Record<string, unknown> | undefined;
  const structuredJson = structured
    ? JSON.stringify(structured, null, 2)
    : JSON.stringify({ document_information: { file_name: document.name, file_type: document.type.toLowerCase() }, summary: 'Processing complete.', metadata: { extraction_method: document.method, page_count: document.pages, word_count: document.words } }, null, 2);
  const meta = document.metadata as Record<string, unknown> | undefined;
  const detectedDates = (meta?.detected_dates as string[]) || (structured?.detected_dates as string[]) || [];
  const measurements = (meta?.detected_measurements as string[]) || (structured?.detected_measurements as string[]) || [];
  const monetary = (meta?.monetary_amounts as string[]) || (structured?.monetary_amounts as string[]) || [];
  const keyValues = (meta?.key_value_fields as Record<string, string>) || (structured?.key_value_fields as Record<string, string>) || {};
  const relevantTerms = (structured?.relevant_detected_terms as string[]) || [];
  return <div className="modal-backdrop" onClick={onClose}><aside className="details-drawer" onClick={(e) => e.stopPropagation()}>
    <div className="drawer-header"><div><p className="eyebrow">DOCUMENT DETAILS</p><h2>{document.name}</h2></div><button className="icon-button" onClick={onClose} aria-label="Close details"><X size={20} /></button></div>
    <div className="drawer-status"><StatusPill status={document.status} /><span>Uploaded {document.uploaded}</span></div>
    {document.status === 'Failed' && document.errorMessage && <div className="detail-error"><AlertCircle size={16} /> {document.errorMessage}</div>}
    <div className="detail-section"><h3>Extracted text</h3><div className="text-preview">{document.extractedText || (document.status === 'Processed' ? 'No text was extracted from this document.' : 'Text will appear here once processing is complete.')}</div></div>
    {document.status === 'Processed' && <KeyValueGrid fields={keyValues} />}
    {document.status === 'Processed' && <DetailList icon={Calendar} title="Detected dates" items={detectedDates} />}
    {document.status === 'Processed' && <DetailList icon={Ruler} title="Measurements" items={measurements} />}
    {document.status === 'Processed' && <DetailList icon={Banknote} title="Monetary amounts" items={monetary} />}
    {document.status === 'Processed' && <DetailList icon={Tag} title="Relevant terms" items={relevantTerms} />}
    <div className="detail-section"><h3>Structured JSON</h3><pre>{structuredJson}</pre></div>
    <div className="detail-section"><h3>Metadata</h3><div className="metadata-grid">
      <span>File type<strong>{document.type}</strong></span>
      <span>Pages<strong>{document.pages || (meta?.page_count as number) || '—'}</strong></span>
      <span>Word count<strong>{document.words || (meta?.word_count as number) || '—'}</strong></span>
      <span>Extraction<strong>{document.method}</strong></span>
      <span>Processed at<strong>{meta?.processed_timestamp ? new Date(meta.processed_timestamp as string).toLocaleString() : document.uploaded}</strong></span>
    </div></div>
    <div className="hash-block"><span>SHA-256 integrity hash</span><strong>{document.hash}</strong></div>
  </aside></div>;
}

export default App;
