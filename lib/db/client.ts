import { PrismaPg } from "@prisma/adapter-pg";
import { PrismaClient } from "@/generated/prisma/client";
import { getConfig } from "@/lib/config";

export function createPrismaClient(connectionString: string): PrismaClient {
  return new PrismaClient({ adapter: new PrismaPg({ connectionString }) });
}

// Reuse one client across Next.js dev hot reloads instead of opening a new pool each time.
const globalForPrisma = globalThis as unknown as { prisma?: PrismaClient };

export function getPrisma(): PrismaClient {
  globalForPrisma.prisma ??= createPrismaClient(getConfig().DATABASE_URL);
  return globalForPrisma.prisma;
}
