import "dotenv/config";
import { afterAll, describe, expect, it } from "vitest";
import { createPrismaClient } from "@/lib/db/client";

const url = process.env.DATABASE_URL_TEST;
const prisma = url ? createPrismaClient(url) : undefined;

afterAll(async () => prisma?.$disconnect());

describe.skipIf(!url)("postgres test database", () => {
  it("is reachable and is Postgres", async () => {
    const rows = await prisma!.$queryRaw<{ v: string }[]>`SELECT version() AS v`;
    expect(rows[0]?.v).toMatch(/^PostgreSQL/);
  });
});
