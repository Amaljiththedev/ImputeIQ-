/* eslint-disable @next/next/no-img-element */
import { useAppDispatch, useAppSelector } from "@/store/hooks";
import { setActiveDataset, fetchResults } from "@/store/slices/datasetSlice";
import { resetJobs } from "@/store/slices/jobSlice";
import { PlusCircle, FileSpreadsheet, Loader2 } from "lucide-react";
import { formatDistanceToNow } from "date-fns";

export default function Sidebar() {
  const dispatch = useAppDispatch();
  const { datasets, activeDatasetId, loading } = useAppSelector((s) => s.dataset);

  const handleSelectDataset = (id: string | null) => {
    dispatch(resetJobs());
    dispatch(setActiveDataset(id));
    if (id !== null) {
      dispatch(fetchResults(id));
    }
  };

  return (
    <aside className="glass-chrome w-[280px] flex flex-col h-full shrink-0">
      {/* Wordmark */}
      <div className="h-[68px] px-6 flex items-center justify-between border-b border-black/[0.06]">
        <div className="flex items-center gap-2.5">
          <div className="w-7 h-7 rounded-md bg-gray-900 flex items-center justify-center text-white shadow-sm">
            <span className="text-[11px] font-bold tracking-tight">IQ</span>
          </div>
          <span className="text-[17px] font-semibold tracking-[-0.021em] text-gray-900">
            ImputeIQ
          </span>
        </div>
        <button
          onClick={() => handleSelectDataset(null)}
          className="flex items-center gap-1.5 text-[13px] font-medium text-blue-500 hover:text-blue-600 transition-colors duration-200"
        >
          <PlusCircle className="w-4 h-4" strokeWidth={2} />
          <span>New</span>
        </button>
      </div>

      {/* Dataset List */}
      <div className="flex-1 overflow-y-auto px-4 py-5">
        <div className="text-[11px] font-semibold text-gray-500 uppercase tracking-[0.06em] px-2 mb-3">
          Datasets
        </div>
        {loading ? (
          <div className="flex items-center gap-2 px-2 py-3 text-[13px] text-gray-500">
            <Loader2 className="w-4 h-4 animate-spin" />
            <span>Loading…</span>
          </div>
        ) : datasets.length === 0 ? (
          <div className="px-2 py-4 text-[13px] text-gray-500">
            No datasets yet
          </div>
        ) : (
          <div className="space-y-1">
            {datasets.map((ds) => {
              const isActive = ds.id === activeDatasetId;
              return (
                <button
                  key={ds.id}
                  onClick={() => handleSelectDataset(ds.id)}
                  className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-md text-left transition-all duration-200 relative group ${
                    isActive
                      ? "glass-thin text-gray-900"
                      : "text-gray-700 border border-transparent hover:bg-white/50"
                  }`}
                >
                  {isActive && (
                    <div className="absolute left-1 top-1/2 -translate-y-1/2 w-[3px] h-5 bg-blue-500 rounded-full" />
                  )}
                  <FileSpreadsheet
                    className={`w-[18px] h-[18px] shrink-0 transition-colors ${
                      isActive ? "text-blue-500" : "text-gray-400 group-hover:text-gray-600"
                    }`}
                    strokeWidth={1.75}
                  />
                  <div className="overflow-hidden">
                    <div
                      className={`text-[13px] truncate ${
                        isActive ? "font-semibold" : "font-medium"
                      }`}
                    >
                      {ds.filename}
                    </div>
                    <div className="text-[11px] text-gray-500 tabular-nums mt-0.5">
                      {ds.row_count.toLocaleString()} rows &middot; {formatDistanceToNow(new Date(ds.uploaded_at), { addSuffix: true })}
                    </div>
                  </div>
                </button>
              );
            })}
          </div>
        )}
      </div>
    </aside>
  );
}