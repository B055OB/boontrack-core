/**
 * config/routing/reserved-routes.ts
 * BoonTrack Apex Domain Reserved Route Manifest Helper & Type Definitions
 *
 * Single Source of Truth for Route Governance, Normalization, and Namespace Reservation.
 * Manifest SHA-256: FCE2E8FCA08FDA336F46B4EA648D2D139E0B8BE6F20DF2BB951EEBF9FFAC6DAD
 */

import manifest from './reserved-route-manifest.v1.json';

export const RESERVED_ROUTE_MANIFEST_VERSION = manifest.version;
export const RESERVED_ROUTE_MANIFEST_SHA256 = 'FCE2E8FCA08FDA336F46B4EA648D2D139E0B8BE6F20DF2BB951EEBF9FFAC6DAD';

export type ReservedNamespaceKey =
  | 'corporate'
  | 'legal'
  | 'platform'
  | 'tricore'
  | 'documentation'
  | 'operations'
  | 'commercial'
  | 'system_and_internal';

export interface RouteValidationResult {
  valid: boolean;
  normalizedPath: string;
  firstSegment: string;
  subPath: string;
  isReserved: boolean;
  namespace: ReservedNamespaceKey | null;
  error?: string;
  errorCode?: 'INVALID_PATH' | 'PATH_TRAVERSAL' | 'DOUBLE_SLASH' | 'ENCODED_SEPARATOR';
}

// Set of all canonical reserved slugs (lowercase)
export const RESERVED_SLUGS_SET = new Set<string>(
  manifest.reserved_slugs.map((s) => s.toLowerCase().trim())
);

// Map each reserved slug to its namespace
export const SLUG_TO_NAMESPACE_MAP = new Map<string, ReservedNamespaceKey>();
for (const [ns, slugs] of Object.entries(manifest.namespaces)) {
  for (const s of slugs) {
    SLUG_TO_NAMESPACE_MAP.set(s.toLowerCase().trim(), ns as ReservedNamespaceKey);
  }
}

/**
 * Normalizes a slug or path segment:
 * - Trims whitespace
 * - Converts to lowercase
 * - Strips leading and trailing slashes
 */
export function normalizeRouteSegment(raw: string): string {
  if (!raw || typeof raw !== 'string') return '';
  return raw.trim().toLowerCase().replace(/^\/+|\/+$/g, '');
}

/**
 * Validates and normalizes an incoming request pathname:
 * - Rejects percent-encoded separators (%2f, %2F, %5c, %5C)
 * - Rejects path traversal (..)
 * - Rejects double slashes (//)
 * - Normalizes to canonical format
 * - Extracts first segment for segment-aware evaluation
 */
export function validateAndExtractRoute(rawPath: string): RouteValidationResult {
  if (typeof rawPath !== 'string') {
    return {
      valid: false,
      normalizedPath: '',
      firstSegment: '',
      subPath: '',
      isReserved: false,
      namespace: null,
      error: 'Path must be a string',
      errorCode: 'INVALID_PATH',
    };
  }

  const trimmed = rawPath.trim();

  // Reject percent-encoded separators (%2f, %5c)
  if (/%2f|%5c/i.test(trimmed)) {
    return {
      valid: false,
      normalizedPath: '',
      firstSegment: '',
      subPath: '',
      isReserved: false,
      namespace: null,
      error: 'Percent-encoded separators (%2f, %5c) are strictly prohibited.',
      errorCode: 'ENCODED_SEPARATOR',
    };
  }

  // Reject path traversal (..)
  if (/\.\./.test(trimmed) || /%2e%2e/i.test(trimmed)) {
    return {
      valid: false,
      normalizedPath: '',
      firstSegment: '',
      subPath: '',
      isReserved: false,
      namespace: null,
      error: 'Path traversal sequences (..) are strictly prohibited.',
      errorCode: 'PATH_TRAVERSAL',
    };
  }

  // Reject double slashes (//)
  if (/\/{2,}/.test(trimmed)) {
    return {
      valid: false,
      normalizedPath: '',
      firstSegment: '',
      subPath: '',
      isReserved: false,
      namespace: null,
      error: 'Double slashes (//) are strictly prohibited.',
      errorCode: 'DOUBLE_SLASH',
    };
  }

  // Normalize path: leading slash, lowercase, strip trailing slash unless root '/'
  let cleanPath = trimmed.toLowerCase();
  if (!cleanPath.startsWith('/')) {
    cleanPath = '/' + cleanPath;
  }
  if (cleanPath.length > 1 && cleanPath.endsWith('/')) {
    cleanPath = cleanPath.slice(0, -1);
  }

  const segments = cleanPath.split('/').filter(Boolean);
  const firstSegment = segments[0] || '';
  const subPath = segments.length > 1 ? '/' + segments.slice(1).join('/') : '';

  const isReserved = Boolean(firstSegment && RESERVED_SLUGS_SET.has(firstSegment));
  const namespace = isReserved ? SLUG_TO_NAMESPACE_MAP.get(firstSegment) || null : null;

  return {
    valid: true,
    normalizedPath: cleanPath,
    firstSegment,
    subPath,
    isReserved,
    namespace,
  };
}

/**
 * Checks if a given slug is in the Reserved Route Manifest (case-insensitive, segment-aware).
 * Note: 'blogger' does NOT match 'blog'.
 */
export function isReservedRouteSlug(slug: string): boolean {
  const normalized = normalizeRouteSegment(slug);
  if (!normalized) return false;
  return RESERVED_SLUGS_SET.has(normalized);
}

/**
 * Returns the namespace of a reserved slug, or null if not reserved.
 */
export function getReservedSlugNamespace(slug: string): ReservedNamespaceKey | null {
  const normalized = normalizeRouteSegment(slug);
  if (!normalized) return null;
  return SLUG_TO_NAMESPACE_MAP.get(normalized) || null;
}

export class ReservedRouteConflictError extends Error {
  slug: string;
  namespace: string;

  constructor(slug: string, namespace: string) {
    super(
      `Tenant slug conflict: '${slug}' is a reserved platform route under namespace '${namespace}'. It cannot be claimed or onboarded as a tenant storefront.`
    );
    this.name = 'ReservedRouteConflictError';
    this.slug = slug;
    this.namespace = namespace;
    Object.setPrototypeOf(this, new.target.prototype);
  }
}

/**
 * Asserts that a tenant slug is NOT reserved.
 * Throws ReservedRouteConflictError if reserved.
 */
export function assertNotReservedTenantSlug(slug: string): void {
  const normalized = normalizeRouteSegment(slug);
  if (isReservedRouteSlug(normalized)) {
    const ns = getReservedSlugNamespace(normalized) || 'system';
    throw new ReservedRouteConflictError(normalized, ns);
  }
}
