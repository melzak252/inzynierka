const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000';

type HealthResponse = {
  status: string;
  service: string;
  environment: string;
  database: string;
};

export async function getApiHealth(): Promise<HealthResponse> {
  const response = await fetch(`${API_BASE_URL}/api/v1/health`);

  if (!response.ok) {
    throw new Error(`API healthcheck failed with status ${response.status}`);
  }

  return response.json() as Promise<HealthResponse>;
}
