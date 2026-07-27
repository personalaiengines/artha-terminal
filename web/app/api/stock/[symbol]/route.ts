import { NextResponse } from "next/server";
import { fromApi } from "@/lib/api-server";

// Single stock: real fundamentals + real OHLC history only. No mock/generated
// data — ok:false + nulls when the API can't serve it, so gaps are visible.
export async function GET(_req: Request, { params }: { params: Promise<{ symbol: string }> }) {
  const { symbol } = await params;
  const sym = symbol.toUpperCase();
  const live = await fromApi<{ stock: any; history: any[] }>(`/api/stock/${sym}`, 6000);
  if (!live?.stock) return NextResponse.json({ ok: false, stock: null, history: [] });
  return NextResponse.json({
    ok: true,
    stock: { ...live.stock, symbol: sym },
    history: live.history ?? [],
  });
}
