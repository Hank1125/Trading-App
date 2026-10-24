import { getConfig } from "@/lib/config";

export const dynamic = "force-dynamic";

export default function Home() {
  const { DATA_MODE } = getConfig();
  return (
    <main className="mx-auto max-w-3xl p-6">
      <span className="rounded bg-amber-200 px-2 py-1 text-xs font-semibold uppercase">
        {DATA_MODE === "mock" ? "Mock data" : "Live data (replays)"} / Demo points
      </span>
      <h1 className="mt-4 text-2xl font-bold">Meta Market</h1>
      <p className="mt-2 text-zinc-600">
        Experimental simulation using virtual points only. Not affiliated with Supercell or Ubisoft.
      </p>
    </main>
  );
}
