import { redirect } from "next/navigation";

// `/documents` is the default landing page (Frontend Spec section 2). The route
// guard added in T1.4 bounces unauthenticated visitors on to `/login`.
export default function Home() {
  redirect("/documents");
}
