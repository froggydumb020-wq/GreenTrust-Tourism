import mongoose from 'mongoose';

const HotelSchema = new mongoose.Schema({
  hotel_name: { type: String, required: true, trim: true },
  registration_number: { type: String, required: true, trim: true, unique: true, index: true },
  hotel_type: { type: String, trim: true },
  number_of_rooms: { type: Number, min: 0 },
  street_address: { type: String, trim: true },
  city: { type: String, trim: true },
  state: { type: String, trim: true },
  pin_zip: { type: String, trim: true },
  country: { type: String, trim: true },
  contact_person: { type: String, trim: true },
  phone: { type: String, trim: true },
  location: { type: String, trim: true },
  contact: { type: String, trim: true },
  email: { type: String, required: true, lowercase: true, trim: true, unique: true, index: true },
  password_hash: { type: String, required: true, select: false },
}, { timestamps: { createdAt: 'created_at', updatedAt: 'updated_at' } });

const EvidencePackageSchema = new mongoose.Schema({
  package_id: { type: String, required: true, unique: true, index: true },
  hotel: { type: mongoose.Schema.Types.ObjectId, ref: 'Hotel', required: true, index: true },
  package_type: {
    type: String,
    required: true,
    enum: ['Sustainability & Legal', 'Energy & Water', 'Waste Management', 'Environmental Practices'],
    index: true,
  },
  status: { type: String, enum: ['Pending', 'Submitted', 'Processing'], default: 'Pending' },
  submitted_at: { type: Date },
}, { timestamps: { createdAt: 'created_at', updatedAt: 'updated_at' } });

const DocumentSchema = new mongoose.Schema({
  document_id: { type: String, required: true, unique: true, index: true },
  package: { type: mongoose.Schema.Types.ObjectId, ref: 'EvidencePackage', index: true },
  hotel: { type: mongoose.Schema.Types.ObjectId, ref: 'Hotel', required: true, index: true },
  file_name: { type: String, required: true },
  file_type: { type: String, required: true, enum: ['pdf', 'docx', 'png', 'jpg'] },
  file_path: { type: String, required: true },
  file_size: { type: Number },
  document_hash: { type: String },
  status: {
    type: String,
    enum: ['UPLOADED', 'PROCESSING', 'PROCESSED', 'FAILED'],
    default: 'UPLOADED',
    index: true,
  },
  error_message: { type: String },
  uploaded_at: { type: Date, default: Date.now },
  processed_at: { type: Date },
}, { timestamps: { createdAt: 'created_at', updatedAt: 'updated_at' } });

const ExtractedDataSchema = new mongoose.Schema({
  extraction_id: { type: String, required: true, unique: true, index: true },
  document: { type: mongoose.Schema.Types.ObjectId, ref: 'Document', required: true, index: true },
  extracted_text: { type: String },
  structured_data: { type: mongoose.Schema.Types.Mixed },
  confidence: { type: Number, default: 0 },
  metadata: { type: mongoose.Schema.Types.Mixed },
  processed_at: { type: Date, default: Date.now },
}, { timestamps: { createdAt: 'created_at', updatedAt: 'updated_at' } });

export const Hotel = mongoose.model('Hotel', HotelSchema);
export const EvidencePackage = mongoose.model('EvidencePackage', EvidencePackageSchema);
export const Document = mongoose.model('Document', DocumentSchema);
export const ExtractedData = mongoose.model('ExtractedData', ExtractedDataSchema);
