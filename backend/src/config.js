import 'dotenv/config';
import mongoose from 'mongoose';

export const config = {
  mongoUri: process.env.MONGODB_URI,
  port: parseInt(process.env.PORT || '4000', 10),
  processorUrl: process.env.PROCESSOR_URL || 'http://localhost:8000',
  frontendUrl: process.env.FRONTEND_URL || 'http://localhost:5173',
  uploadDir: process.env.UPLOAD_DIR || 'uploads',
  maxFileSize: (parseInt(process.env.MAX_FILE_SIZE_MB || '20', 10)) * 1024 * 1024,
};

const allowedMimes = new Map([
  ['application/pdf', 'pdf'],
  ['application/vnd.openxmlformats-officedocument.wordprocessingml.document', 'docx'],
  ['image/png', 'png'],
  ['image/jpeg', 'jpg'],
]);

export function detectExtension(mimetype, originalname) {
  if (allowedMimes.has(mimetype)) return allowedMimes.get(mimetype);
  const fallback = originalname.toLowerCase().split('.').pop();
  return ['pdf', 'docx', 'png', 'jpg'].includes(fallback) ? fallback : null;
}

export function isAllowedFile(mimetype, originalname) {
  return detectExtension(mimetype, originalname) !== null;
}

export async function connectMongo() {
  if (!config.mongoUri) {
    console.warn('[db] MONGODB_URI not set — API will start without persistence. Set it in backend/.env to enable MongoDB.');
    return false;
  }
  try {
    await mongoose.connect(config.mongoUri);
    console.log('[db] Connected to MongoDB');
    return true;
  } catch (error) {
    console.error('[db] MongoDB connection failed:', error.message);
    return false;
  }
}
