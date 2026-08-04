import { useCallback, useState } from "react";
import { UploadCloud, Loader2 } from "lucide-react";
import { uploadDataset, startRecommend } from "@/lib/api";
import { useAppDispatch } from "@/store/hooks";
import { addDataset, setActiveDataset } from "@/store/slices/datasetSlice";
import { setPhase, setCurrentJobId, addLog } from "@/store/slices/jobSlice";

export default function UploadDropzone() {
  const dispatch = useAppDispatch();
  const [isDragging, setIsDragging] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleUpload = async (file: File) => {
    if (!file.name.endsWith(".csv")) {
      setError("Please upload a CSV file.");
      return;
    }

    setIsUploading(true);
    setError(null);
    try {
      const dataset = await uploadDataset(file);
      dispatch(addDataset(dataset));
      dispatch(setActiveDataset(dataset.id));
      dispatch(setPhase("validating"));
      dispatch(addLog("Dataset uploaded successfully. Initializing Data Validation & placeholder analysis..."));
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to upload file.");
    } finally {
      setIsUploading(false);
    }
  };

  const onDrop = useCallback((e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setIsDragging(false);
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      handleUpload(e.dataTransfer.files[0]);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dispatch]);

  return (
    <div className="w-full">
      <div
        onDragOver={(e) => { e.preventDefault(); setIsDragging(true); }}
        onDragLeave={() => setIsDragging(false)}
        onDrop={onDrop}
        className={`relative border border-dashed rounded-xl p-10 flex flex-col items-center justify-center transition-all duration-300 ${
          isDragging
            ? "border-blue-500 bg-blue-50/70 scale-[1.01]"
            : "border-gray-300 hover:border-gray-400 bg-white/40"
        } ${isUploading ? "opacity-50 pointer-events-none" : ""}`}
      >
        <input
          type="file"
          accept=".csv"
          className="absolute inset-0 w-full h-full opacity-0 cursor-pointer"
          onChange={(e) => {
            if (e.target.files && e.target.files.length > 0) {
              handleUpload(e.target.files[0]);
            }
          }}
        />

        {isUploading ? (
          <div className="flex flex-col items-center">
            <Loader2 className="w-8 h-8 text-blue-500 mb-4 animate-spin" strokeWidth={1.75} />
            <p className="text-[14px] text-gray-900 font-medium">Uploading dataset…</p>
          </div>
        ) : (
          <div className="flex flex-col items-center">
            <div className="w-14 h-14 rounded-full glass flex items-center justify-center mb-4">
              <UploadCloud className="w-6 h-6 text-blue-500" strokeWidth={1.5} />
            </div>
            <p className="text-[14px] text-gray-900 font-medium mb-1">
              Drop a CSV file here or click to browse
            </p>
            <p className="text-[12px] text-gray-500">Maximum file size 50 MB</p>
          </div>
        )}
      </div>
      {error && (
        <div className="mt-4 px-4 py-3 bg-danger-bg text-danger-fg rounded-md text-[13px] flex items-center justify-center">
          {error}
        </div>
      )}
    </div>
  );
}
