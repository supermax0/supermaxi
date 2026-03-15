import { env } from "../../config/env.js";

function authHeaders() {
  return env.QDRANT_API_KEY ? { "api-key": env.QDRANT_API_KEY } : {};
}

export async function ensureCollection(vectorSize = 1536): Promise<void> {
  const url = `${env.QDRANT_URL}/collections/${env.QDRANT_COLLECTION}`;
  const getRes = await fetch(url, { headers: { ...authHeaders() } });
  if (getRes.ok) return;

  await fetch(url, {
    method: "PUT",
    headers: {
      "content-type": "application/json",
      ...authHeaders(),
    },
    body: JSON.stringify({
      vectors: {
        size: vectorSize,
        distance: "Cosine",
      },
    }),
  });
}

export async function upsertVectorPoint(pointId: string, vector: number[], payload: Record<string, unknown>) {
  const url = `${env.QDRANT_URL}/collections/${env.QDRANT_COLLECTION}/points`;
  await fetch(url, {
    method: "PUT",
    headers: {
      "content-type": "application/json",
      ...authHeaders(),
    },
    body: JSON.stringify({
      points: [
        {
          id: pointId,
          vector,
          payload,
        },
      ],
    }),
  });
}
