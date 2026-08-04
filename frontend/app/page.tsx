"use client";

import Sidebar from "@/components/layout/Sidebar";
import MainPanel from "@/components/layout/MainPanel";

export default function Home() {
  return (
    <div className="iq-ambient flex h-screen w-full overflow-hidden text-gray-900">
      <Sidebar />
      <MainPanel />
    </div>
  );
}
