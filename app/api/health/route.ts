import { getConfig } from "@/lib/config";
import { getPrisma } from "@/lib/db/client";

export const dynamic = "force-dynamic";

export async function GET() {
  try {
    const { DATA_MODE } = getConfig();
    await getPrisma().$queryRaw`SELECT 1`;
    return Response.json({ ok: true, dataMode: DATA_MODE, database: "reachable" });
  } catch (err) {
    // Report the failure class only; never echo connection strings or tokens.
    const reason = err instanceof Error ? err.name : "UnknownError";
    return Response.json({ ok: false, error: reason }, { status: 503 });
  }
}
