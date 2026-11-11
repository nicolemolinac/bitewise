export function parseApiResponse(response: {
  ok: boolean;
  status: number;
  text(): Promise<string>;
}): Promise<any>;
