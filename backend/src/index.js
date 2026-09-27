import express from 'express';
import cors from 'cors';
import multer from 'multer';
import crypto from 'node:crypto';
import path from 'node:path';
import fs from 'node:fs';
import { config, connectMongo, isAllowedFile, detectExtension } from './config.js';
import { Hotel, Document, ExtractedData, EvidencePackage } from './models.js';
import { processDocument, ensurePackage } from './processor.js';
import { requireAuth, signToken, sanitizeHotel } from './auth.js';
import bcrypt from 'bcryptjs';

const app = express();

app.use(cors({ origin: config.frontendUrl, credentials: true }));
app.use(express.json());

fs.mkdirSync(path.resolve(config.uploadDir), { recursive: true });

const upload = multer({
  dest: path.resolve(config.uploadDir),
  limits: { fileSize: config.maxFileSize },
  fileFilter: (_req, file, cb) => {
    if (isAllowedFile(file.mimetype, file.originalname)) cb(null, true);
    else cb(new Error('Only PDF, DOCX, PNG, and JPG files are allowed'));
  },
});

function shortHash() { return crypto.randomBytes(6).toString('hex'); }

app.get('/api/health', (_req, res) => {
  res.json({ status: 'ok', service: 'greentrust-backend', timestamp: new Date().toISOString() });
});

const HOTEL_TYPES = ['Resort', 'Hotel', 'Boutique Hotel', 'Homestay', 'Villa', 'Lodge', 'Guest House', 'Hostel', 'Serviced Apartment', 'Eco Lodge'];
const REQUIRED_REGISTER = ['hotel_name', 'registration_number', 'email', 'password', 'contact_person', 'phone', 'street_address', 'city', 'state', 'pin_zip', 'country'];

app.post('/api/auth/register', async (req, res) => {
  try {
    const body = req.body || {};
    const missing = REQUIRED_REGISTER.filter((f) => !body[f] || !String(body[f]).trim());
    if (missing.length) return res.status(400).json({ error: `Missing required fields: ${missing.join(', ')}` });

    const email = String(body.email).toLowerCase().trim();
    const registration_number = String(body.registration_number).trim();
    const password = String(body.password);
    if (password.length < 8) return res.status(400).json({ error: 'Password must be at least 8 characters' });
    if (body.confirm_password !== undefined && String(body.confirm_password) !== password) {
      return res.status(400).json({ error: 'Passwords do not match' });
    }
    if (body.hotel_type && !HOTEL_TYPES.includes(body.hotel_type)) {
      return res.status(400).json({ error: 'Invalid hotel type' });
    }

    const existing = await Hotel.findOne({ $or: [{ email }, { registration_number }] });
    if (existing) {
      if (existing.email === email) return res.status(409).json({ error: 'An account with this email already exists' });
      return res.status(409).json({ error: 'This registration number is already registered' });
    }

    const password_hash = await bcrypt.hash(password, 12);
    const rooms = body.number_of_rooms !== undefined && body.number_of_rooms !== ''
      ? parseInt(body.number_of_rooms, 10)
      : undefined;
    if (rooms !== undefined && (Number.isNaN(rooms) || rooms < 0)) {
      return res.status(400).json({ error: 'Number of rooms must be a positive number' });
    }

    const hotel = await Hotel.create({
      hotel_name: String(body.hotel_name).trim(),
      registration_number,
      hotel_type: body.hotel_type ? String(body.hotel_type).trim() : undefined,
      number_of_rooms: rooms,
      street_address: String(body.street_address).trim(),
      city: String(body.city).trim(),
      state: String(body.state).trim(),
      pin_zip: String(body.pin_zip).trim(),
      country: String(body.country).trim(),
      contact_person: String(body.contact_person).trim(),
      phone: String(body.phone).trim(),
      email,
      password_hash,
      location: `${body.city}, ${body.state}, ${body.country}`,
      contact: `${body.contact_person} · ${body.phone}`,
    });

    const token = signToken(hotel);
    res.status(201).json({ token, hotel: sanitizeHotel(hotel) });
  } catch (error) {
    if (error.code === 11000) {
      const field = Object.keys(error.keyPattern || {})[0] || 'field';
      return res.status(409).json({ error: `That ${field} is already registered` });
    }
    res.status(400).json({ error: error.message });
  }
});

app.post('/api/auth/login', async (req, res) => {
  try {
    const { email, password } = req.body || {};
    if (!email || !password) return res.status(400).json({ error: 'Email and password are required' });
    const hotel = await Hotel.findOne({ email: String(email).toLowerCase().trim() }).select('+password_hash');
    if (!hotel) return res.status(401).json({ error: 'Invalid email or password' });
    const ok = await bcrypt.compare(String(password), hotel.password_hash);
    if (!ok) return res.status(401).json({ error: 'Invalid email or password' });
    const token = signToken(hotel);
    res.json({ token, hotel: sanitizeHotel(hotel) });
  } catch (error) {
    res.status(500).json({ error: error.message });
  }
});

app.get('/api/auth/me', requireAuth, async (req, res) => {
  res.json({ hotel: sanitizeHotel(req.hotel) });
});

app.post('/api/hotels', async (req, res) => {
  try {
    const { hotel_name, location, contact, registration_number } = req.body || {};
    if (!hotel_name) return res.status(400).json({ error: 'hotel_name is required' });

    if (registration_number) {
      const existing = await Hotel.findOne({ registration_number });
      if (existing) return res.status(200).json(existing);
    }

    const hotel = await Hotel.create({ hotel_name, location, contact, registration_number });
    res.status(201).json(hotel);
  } catch (error) {
    res.status(400).json({ error: error.message });
  }
});

app.get('/api/hotels/:hotelId', async (req, res) => {
  try {
    const hotel = await Hotel.findById(req.params.hotelId);
    if (!hotel) return res.status(404).json({ error: 'Hotel not found' });
    res.json(hotel);
  } catch (error) {
    res.status(500).json({ error: error.message });
  }
});

app.post('/api/documents/upload', requireAuth, upload.single('file'), async (req, res) => {
  if (!req.file) return res.status(400).json({ error: 'No file uploaded' });
  const hotelId = req.hotel._id.toString();
  const packageType = req.body.package_type || 'Energy & Water';

  const fileType = detectExtension(req.file.mimetype, req.file.originalname);
  if (!fileType) return res.status(400).json({ error: 'Unsupported file type' });

  try {
    const hotel = await Hotel.findById(hotelId);
    if (!hotel) return res.status(404).json({ error: 'Hotel not found' });

    const pkg = await ensurePackage(hotelId, packageType);
    const document = await Document.create({
      document_id: `doc-${shortHash()}`,
      package: pkg._id,
      hotel: hotelId,
      file_name: req.file.originalname,
      file_type: fileType,
      file_path: req.file.path,
      file_size: req.file.size,
      status: 'UPLOADED',
      uploaded_at: new Date(),
    });

    processDocument(document).catch((err) => console.error('[async] processing error:', err.message));

    res.status(202).json({ message: 'Document uploaded and processing started', document });
  } catch (error) {
    res.status(500).json({ error: error.message });
  }
});

app.get('/api/documents/:id', async (req, res) => {
  try {
    const document = await Document.findOne({ document_id: req.params.id }).populate('hotel').populate('package');
    if (!document) return res.status(404).json({ error: 'Document not found' });
    const extracted = await ExtractedData.findOne({ document: document._id }).sort({ processed_at: -1 });
    res.json({ document, extracted_data: extracted });
  } catch (error) {
    res.status(500).json({ error: error.message });
  }
});

app.get('/api/hotels/:hotelId/documents', async (req, res) => {
  try {
    const documents = await Document.find({ hotel: req.params.hotelId }).populate('package').sort({ uploaded_at: -1 });
    res.json({ documents });
  } catch (error) {
    res.status(500).json({ error: error.message });
  }
});

app.get('/api/packages/:hotelId', async (req, res) => {
  try {
    const packages = await EvidencePackage.find({ hotel: req.params.hotelId }).sort({ created_at: -1 });
    res.json({ packages });
  } catch (error) {
    res.status(500).json({ error: error.message });
  }
});

const server = app.listen(config.port, async () => {
  console.log(`[api] GreenTrust backend on http://localhost:${config.port}`);
  await connectMongo();
});

export { server };
