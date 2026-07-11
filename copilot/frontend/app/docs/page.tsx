"use client";
import * as React from "react";
import useSWR from "swr";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";

interface ToolMeta {
  name: string; description: string; dangerous: boolean;
  args_schema: { properties?: Record<string, unknown>; required?: string[] };
}

export default function DocsPage() {
  const { data } = useSWR("tools", async () => {
    const r = await fetch("/api/tools");
    return (await r.json()) as { tools: ToolMeta[] };
  });
  return (
    <div className="max-w-5xl mx-auto p-6 space-y-6">
      <div>
        <h1 className="text-2xl font-extrabold text-ink">Tools reference</h1>
        <p className="text-sm text-ink-500 mt-1">
          The copilot drives the platform through these tools.
        </p>
      </div>
      {(data?.tools ?? []).map((t) => (
        <Card key={t.name}>
          <CardHeader className="flex items-center gap-2">
            <code className="font-bold text-sm">{t.name}</code>
            {t.dangerous ? <Badge tone="warn">dangerous</Badge> : <Badge tone="ok">safe</Badge>}
          </CardHeader>
          <CardBody className="space-y-2 text-sm">
            <p className="text-ink-700">{t.description}</p>
            {t.args_schema?.properties && Object.keys(t.args_schema.properties).length > 0 ? (
              <details className="text-xs">
                <summary className="cursor-pointer text-ink-500">arguments</summary>
                <pre className="bg-ink-50 border border-ink-200 rounded p-2 mt-1 overflow-x-auto">
{JSON.stringify(t.args_schema, null, 2)}
                </pre>
              </details>
            ) : null}
          </CardBody>
        </Card>
      ))}
    </div>
  );
}
