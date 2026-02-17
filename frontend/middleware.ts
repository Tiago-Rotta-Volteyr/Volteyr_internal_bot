import { createMiddlewareClient } from "@supabase/auth-helpers-nextjs";
import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

const CHROME_DEVTOOLS_PATH = "/.well-known/appspecific/com.chrome.devtools.json";

export async function middleware(req: NextRequest) {
  if (req.nextUrl.pathname === CHROME_DEVTOOLS_PATH) {
    return new NextResponse(null, { status: 204 });
  }
  try {
    const res = NextResponse.next();
    const supabase = createMiddlewareClient({ req, res });
    await supabase.auth.getSession();

    const {
      data: { session },
    } = await supabase.auth.getSession();

    const isLoginPage = req.nextUrl.pathname === "/login";

    if (!session && !isLoginPage) {
      const url = req.nextUrl.clone();
      url.pathname = "/login";
      return NextResponse.redirect(url);
    }

    if (session && isLoginPage) {
      const url = req.nextUrl.clone();
      url.pathname = "/";
      return NextResponse.redirect(url);
    }

    return res;
  } catch {
    return NextResponse.next();
  }
}

export const config = {
  matcher: ["/", "/login", "/.well-known/appspecific/com.chrome.devtools.json"],
};
