/** Client-side validation mirroring the backend's rules in `schemas/auth.py`. */

export const MIN_PASSWORD_LENGTH = 8;

/**
 * bcrypt hashes at most 72 bytes, so the API rejects anything longer. Checked
 * in bytes, not characters: a 40-character accented password is already 80.
 */
export const MAX_PASSWORD_BYTES = 72;

export function passwordByteLength(password: string): number {
  return new TextEncoder().encode(password).length;
}

export function validateEmail(email: string): string | null {
  if (!email.trim()) {
    return "Email is required.";
  }
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim())) {
    return "Enter a valid email address.";
  }
  return null;
}

/** Mirrors ALLOWED_EXTENSIONS in the backend's text_extraction service. */
export const ALLOWED_EXTENSIONS = [".txt", ".md", ".pdf"] as const;

/** Mirrors MAX_UPLOAD_MB. The server stays the authority; this saves a round trip. */
export const MAX_UPLOAD_MB = 10;
export const MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024;

export function validateUploadFile(file: File): string | null {
  const name = file.name.toLowerCase();

  if (!ALLOWED_EXTENSIONS.some((extension) => name.endsWith(extension))) {
    return `"${file.name}" is not a supported file type. Allowed: ${ALLOWED_EXTENSIONS.join(", ")}.`;
  }
  if (file.size === 0) {
    return `"${file.name}" is empty.`;
  }
  if (file.size > MAX_UPLOAD_BYTES) {
    return `"${file.name}" is larger than the ${MAX_UPLOAD_MB}MB limit.`;
  }

  return null;
}

export function validatePassword(password: string): string | null {
  if (!password) {
    return "Password is required.";
  }
  if (password.length < MIN_PASSWORD_LENGTH) {
    return `Password must be at least ${MIN_PASSWORD_LENGTH} characters.`;
  }
  if (passwordByteLength(password) > MAX_PASSWORD_BYTES) {
    return `Password must be at most ${MAX_PASSWORD_BYTES} bytes.`;
  }
  return null;
}
