import { NextResponse } from 'next/server';
import type { NextRequest } from 'next/server';

// Public-facing pages allowed on the custom quote domain
const PUBLIC_PAGES = [
  '/get-quote',
  '/start-quote',
  '/quote-confirmation',
  '/privacy',
  '/survey',
];

// Static assets and API routes should always pass through
const PASSTHROUGH_PREFIXES = [
  '/api/',
  '/_next/',
  '/carrier-logos/',
  '/favicon',
  '/robots.txt',
  '/sitemap',
];

export function middleware(request: NextRequest) {
  const hostname = request.headers.get('host') || '';
  const pathname = request.nextUrl.pathname;

  // Only apply restrictions on the quote subdomain
  if (hostname.includes('quote.betterchoiceins.com')) {
    // Allow static assets and API calls
    if (PASSTHROUGH_PREFIXES.some(prefix => pathname.startsWith(prefix))) {
      return NextResponse.next();
    }

    // Allow public pages
    if (PUBLIC_PAGES.some(page => pathname.startsWith(page))) {
      return NextResponse.next();
    }

    // Root → redirect to /get-quote
    if (pathname === '/' || pathname === '') {
      return NextResponse.redirect(new URL('/get-quote', request.url));
    }

    // Everything else (login, dashboard, analytics, etc.) → redirect to /get-quote
    return NextResponse.redirect(new URL('/get-quote', request.url));
  }

  // On the Render domain (better-choice-web.onrender.com), allow everything
  return NextResponse.next();
}

export const config = {
  matcher: [
    // Match all paths except static files
    '/((?!_next/static|_next/image|favicon.ico).*)',
  ],
};
