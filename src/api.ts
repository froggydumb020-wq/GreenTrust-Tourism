export type DocStatus = 'Processed' | 'Processing' | 'Failed';

export type View = 'dashboard' | 'packages' | 'upload' | 'documents' | 'profile';

export type DocumentItem = {
  id: string;
  name: string;
  type: string;
  package: string;
  uploaded: string;
  uploadedAt: number;
  status: DocStatus;
  size: string;
  hash: string;
  method: string;
  pages: number;
  words: number;
  errorMessage?: string;
  extractedText?: string;
  structuredData?: unknown;
  metadata?: Record<string, unknown>;
};

export type Hotel = {
  _id: string;
  hotel_name: string;
  location?: string;
  contact?: string;
  registration_number?: string;
  hotel_type?: string;
  number_of_rooms?: number;
  street_address?: string;
  city?: string;
  state?: string;
  pin_zip?: string;
  country?: string;
  contact_person?: string;
  phone?: string;
  email?: string;
};

const TOKEN_KEY = 'greentrust_token';
const HOTEL_KEY = 'greentrust_hotel';

export function getToken(): string | null {
  try { return localStorage.getItem(TOKEN_KEY); } catch { return null; }
}

export function getStoredHotel(): Hotel | null {
  try { const raw = localStorage.getItem(HOTEL_KEY); return raw ? JSON.parse(raw) as Hotel : null; } catch { return null; }
}

export function setSession(token: string, hotel: Hotel): void {
  try { localStorage.setItem(TOKEN_KEY, token); localStorage.setItem(HOTEL_KEY, JSON.stringify(hotel)); } catch { /* ignore */ }
}

export function clearSession(): void {
  try { localStorage.removeItem(TOKEN_KEY); localStorage.removeItem(HOTEL_KEY); } catch { /* ignore */ }
}

export async function registerHotel(data: Record<string, string>): Promise<{ token: string; hotel: Hotel }> {
  const res = await apiFetch<{ token: string; hotel: Hotel }>('/auth/register', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
  setSession(res.token, res.hotel);
  return res;
}

export async function loginHotel(email: string, password: string): Promise<{ token: string; hotel: Hotel }> {
  const res = await apiFetch<{ token: string; hotel: Hotel }>('/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password }),
  });
  setSession(res.token, res.hotel);
  return res;
}

export async function fetchMe(): Promise<Hotel | null> {
  const token = getToken();
  if (!token) return null;
  try {
    const res = await apiFetch<{ hotel: Hotel }>('/auth/me', {
      headers: { Authorization: `Bearer ${token}` },
    });
    setSession(token, res.hotel);
    return res.hotel;
  } catch {
    clearSession();
    return null;
  }
}

const API_BASE = import.meta.env.VITE_API_URL || '/api';

let cachedHotelId: string | null = null;

export const PACKAGE_TYPES = [
  'Sustainability & Legal',
  'Energy & Water',
  'Waste Management',
  'Environmental Practices',
] as const;

export type PackageInfo = {
  name: string;
  count: number;
  processed: number;
  processing: number;
  failed: number;
  progress: number;
};

export function computePackageStats(docs: DocumentItem[]): PackageInfo[] {
  return PACKAGE_TYPES.map((pkgType) => {
    const pkgDocs = docs.filter((d) => d.package === pkgType);
    const processed = pkgDocs.filter((d) => d.status === 'Processed').length;
    const processing = pkgDocs.filter((d) => d.status === 'Processing').length;
    const failed = pkgDocs.filter((d) => d.status === 'Failed').length;
    const total = pkgDocs.length;
    const progress = total > 0 ? Math.round((processed / total) * 100) : 0;
    return { name: pkgType, count: total, processed, processing, failed, progress };
  });
}

const mockDocuments: DocumentItem[] = [
  { id: 'doc-2401', name: 'Water Consumption Statement — Q2 2026.pdf', type: 'PDF', package: 'Energy & Water', uploaded: 'Today, 9:42 AM', uploadedAt: Date.now() - 2 * 3600_000, status: 'Processed', size: '2.4 MB', hash: 'a8f4e2c91d3b5f7e2c9a4b6d8e0f1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9', method: 'PDF text extraction', pages: 4, words: 1284, extractedText: 'Water consumption statement\nReporting period: April — June 2026\n\nTotal water consumed: 1,284 m³\nAverage daily consumption: 14.2 m³\nMunicipal supply and rainwater harvesting sources.', structuredData: { document_information: { file_name: 'Water Consumption Statement — Q2 2026.pdf', file_type: 'pdf' }, summary: 'Resource consumption statement for Q2 2026.', key_excerpts: ['Total water consumed: 1,284 m³', 'Average daily consumption: 14.2 m³'], relevant_detected_terms: ['water', 'consumption', 'm³'], detected_measurements: ['1,284 m³', '14.2 m³'] } },
  { id: 'doc-2398', name: 'Environmental Policy & Commitments.docx', type: 'DOCX', package: 'Sustainability & Legal', uploaded: 'Yesterday, 4:18 PM', uploadedAt: Date.now() - 26 * 3600_000, status: 'Processed', size: '841 KB', hash: 'd31bc04a7e9f1c2d3b4a5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6b7c8d9e0f', method: 'DOCX paragraph & table', pages: 6, words: 2380, extractedText: 'Environmental Policy & Commitments\n\nThis document outlines our sustainability commitments...', structuredData: { document_information: { file_name: 'Environmental Policy & Commitments.docx', file_type: 'docx' }, summary: 'Environmental policy and sustainability commitments document.', key_excerpts: ['This document outlines our sustainability commitments'] } },
  { id: 'doc-2397', name: 'Waste Collection Receipt — May.jpg', type: 'JPG', package: 'Waste Management', uploaded: 'Yesterday, 1:05 PM', uploadedAt: Date.now() - 27 * 3600_000, status: 'Processing', size: '1.8 MB', hash: 'Pending', method: 'OCR queued', pages: 1, words: 0 },
  { id: 'doc-2391', name: 'Operating License 2026.pdf', type: 'PDF', package: 'Sustainability & Legal', uploaded: 'Jun 18, 2026', uploadedAt: Date.now() - 98 * 24 * 3600_000, status: 'Failed', size: '560 KB', hash: 'Not available', method: 'Could not read file', pages: 0, words: 0, errorMessage: 'The file appears to be corrupted or password-protected.' },
  { id: 'doc-2389', name: 'Solar Water Heating Overview.png', type: 'PNG', package: 'Energy & Water', uploaded: 'Jun 16, 2026', uploadedAt: Date.now() - 100 * 24 * 3600_000, status: 'Processed', size: '3.1 MB', hash: 'f21ab09d0ac3e5f7a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5', method: 'Tesseract OCR', pages: 1, words: 463, extractedText: 'Solar Water Heating Overview\n\nInstalled capacity: 15 kW\nAnnual energy saved: 18,000 kWh', structuredData: { document_information: { file_name: 'Solar Water Heating Overview.png', file_type: 'png' }, summary: 'Solar water heating system overview.', key_excerpts: ['Installed capacity: 15 kW', 'Annual energy saved: 18,000 kWh'], relevant_detected_terms: ['energy', 'solar', 'kWh'] } },
];

function formatSize(bytes?: number): string {
  if (!bytes) return '—';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function formatUploaded(date?: Date | string | number): string {
  if (!date) return '—';
  const d = typeof date === 'object' ? date : new Date(date);
  const diff = Date.now() - d.getTime();
  if (diff < 60_000) return 'Just now';
  if (diff < 3600_000) return `${Math.floor(diff / 60_000)} min ago`;
  if (diff < 24 * 3600_000) return `Today, ${d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}`;
  if (diff < 48 * 3600_000) return 'Yesterday';
  return d.toLocaleDateString([], { month: 'short', day: 'numeric', year: 'numeric' });
}

function mapStatus(status: string): DocStatus {
  if (status === 'PROCESSED') return 'Processed';
  if (status === 'FAILED') return 'Failed';
  return 'Processing';
}

function mapDocument(raw: any, pkgName?: string): DocumentItem {
  const meta = raw.extracted_data?.metadata || {};
  const structured = raw.extracted_data?.structured_data || {};
  return {
    id: raw.document?.document_id || raw.document_id || 'unknown',
    name: raw.document?.file_name || raw.file_name || 'Untitled',
    type: (raw.document?.file_type || raw.file_type || '').toUpperCase(),
    package: pkgName || raw.document?.package?.package_type || raw.package?.package_type || 'Unassigned',
    uploaded: formatUploaded(raw.document?.uploaded_at || raw.uploaded_at),
    uploadedAt: new Date(raw.document?.uploaded_at || raw.uploaded_at || Date.now()).getTime(),
    status: mapStatus(raw.document?.status || raw.status || 'PROCESSING'),
    size: formatSize(raw.document?.file_size || raw.file_size),
    hash: raw.document?.document_hash || raw.document_hash || 'Pending',
    method: meta.extraction_method || raw.document?.error_message || 'Processing...',
    pages: meta.page_count || 0,
    words: meta.word_count || 0,
    errorMessage: raw.document?.error_message,
    extractedText: raw.extracted_data?.extracted_text,
    structuredData: structured,
    metadata: meta,
  };
}

async function apiFetch<T>(path: string, options?: RequestInit): Promise<T> {
  const token = getToken();
  const headers = new Headers(options?.headers || {});
  if (token && !headers.has('Authorization')) headers.set('Authorization', `Bearer ${token}`);
  const res = await fetch(`${API_BASE}${path}`, { ...options, headers });
  if (!res.ok) throw new Error(`API ${res.status}: ${await res.text().catch(() => res.statusText)}`);
  return res.json() as Promise<T>;
}

export async function checkBackend(): Promise<boolean> {
  try {
    await apiFetch<{ status: string }>('/health');
    return true;
  } catch {
    return false;
  }
}

export async function ensureHotel(): Promise<{ hotelId: string; hotel: Hotel } | null> {
  if (cachedHotelId) {
    try {
      const hotel = await apiFetch<Hotel>(`/hotels/${cachedHotelId}`);
      return { hotelId: cachedHotelId, hotel };
    } catch { cachedHotelId = null; }
  }
  try {
    const hotel = await apiFetch<Hotel>('/hotels', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        hotel_name: 'Azure Mornings',
        location: 'Kochi, Kerala',
        contact: 'operations@azuremornings.com',
        registration_number: 'AM-HOTEL-2026-014',
      }),
    });
    cachedHotelId = hotel._id;
    return { hotelId: hotel._id, hotel };
  } catch {
    return null;
  }
}

export async function fetchDocuments(hotelId: string): Promise<DocumentItem[]> {
  const data = await apiFetch<{ documents: any[] }>(`/hotels/${hotelId}/documents`);
  return data.documents.map((doc) => mapDocument({ document: doc }));
}

export async function fetchPackages(hotelId: string): Promise<any[]> {
  const data = await apiFetch<{ packages: any[] }>(`/packages/${hotelId}`);
  return data.packages;
}

export async function fetchDocumentDetail(documentId: string): Promise<DocumentItem> {
  const data = await apiFetch<{ document: any; extracted_data: any }>(`/documents/${documentId}`);
  return mapDocument(data);
}

export async function uploadDocument(file: File, hotelId: string, packageType: string): Promise<DocumentItem> {
  const formData = new FormData();
  formData.append('file', file);
  formData.append('package_type', packageType);
  const data = await apiFetch<{ document: any } & { message?: string }>('/documents/upload', { method: 'POST', body: formData });
  return mapDocument(data);
}

export function getMockDocuments(): DocumentItem[] {
  return mockDocuments;
}

export function createMockUpload(file: File, packageType: string): DocumentItem {
  const ext = file.name.split('.').pop()?.toUpperCase() || 'FILE';
  return {
    id: `doc-mock-${Date.now()}`,
    name: file.name,
    type: ext,
    package: packageType,
    uploaded: 'Just now',
    uploadedAt: Date.now(),
    status: 'Processing',
    size: formatSize(file.size),
    hash: 'Pending',
    method: ext === 'PDF' ? 'PDF extraction queued' : ext === 'DOCX' ? 'DOCX extraction queued' : 'OCR queued',
    pages: 0,
    words: 0,
  };
}

export function mockComplete(doc: DocumentItem): DocumentItem {
  const ext = doc.type;
  const mockText = 'Sample extracted text from uploaded document.\n\nThis document has been processed and text has been extracted successfully.\nKey data points are identified and structured.';
  const mockStructured = {
    document_information: { file_name: doc.name, file_type: ext.toLowerCase() },
    summary: 'Sample document processed in offline mode.',
    key_excerpts: ['Sample extracted text from uploaded document.'],
    relevant_detected_terms: [],
    detected_measurements: [],
  };
  return {
    ...doc,
    status: 'Processed',
    hash: 'c42e19fb3d84' + 'a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1',
    method: ext === 'PDF' ? 'PDF text extraction' : ext === 'DOCX' ? 'DOCX paragraph & table' : 'Tesseract OCR',
    pages: ext === 'PDF' ? 2 : 1,
    words: 782,
    extractedText: mockText,
    structuredData: mockStructured,
    metadata: { file_type: ext.toLowerCase(), page_count: ext === 'PDF' ? 2 : 1, word_count: 782, extraction_method: 'Offline mock' },
  };
}
