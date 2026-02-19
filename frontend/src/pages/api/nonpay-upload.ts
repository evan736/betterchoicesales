import type { NextApiRequest, NextApiResponse } from 'next';

export const config = {
  api: {
    bodyParser: {
      sizeLimit: '25mb',
    },
  },
};

export default async function handler(req: NextApiRequest, res: NextApiResponse) {
  if (req.method !== 'POST') {
    return res.status(405).json({ detail: 'Method not allowed' });
  }

  const apiUrl = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
  const dryRun = req.query.dry_run || 'false';

  try {
    const response = await fetch(`${apiUrl}/api/nonpay/upload-b64?dry_run=${dryRun}`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': req.headers.authorization || '',
      },
      body: JSON.stringify(req.body),
    });

    const text = await response.text();
    let data;
    try {
      data = JSON.parse(text);
    } catch {
      data = { detail: `Backend error (${response.status}): ${text.slice(0, 500)}` };
    }
    return res.status(response.status).json(data);
  } catch (error: any) {
    return res.status(500).json({ detail: `Proxy error: ${error.message}` });
  }
}
