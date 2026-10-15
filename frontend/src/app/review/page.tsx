"use client";

import TopBar, { Page } from "@/components/ui/TopBar";

export default function ReviewPage() {
  return (
    <>
      <TopBar crumbs={[{ label: "Workspace" }, { label: "Agent review" }]} />
      <Page>
        <h1 className="m-0 text-[26px] font-semibold tracking-[-0.025em]">Agent review</h1>
      </Page>
    </>
  );
}
