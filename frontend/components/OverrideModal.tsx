import { useState } from "react";
import { X } from "lucide-react";

interface OverrideModalProps {
  columnName: string;
  onClose: () => void;
  onApply: (reason: string) => void;
}

export default function OverrideModal({ columnName, onClose, onApply }: OverrideModalProps) {
  const [selected, setSelected] = useState<string>("not_sure");

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-gray-900/40 backdrop-blur-sm animate-in fade-in duration-200">
      <div className="bg-white rounded-2xl shadow-xl max-w-lg w-full overflow-hidden animate-in zoom-in-95 duration-200">
        <div className="px-6 py-4 border-b border-gray-100 flex items-center justify-between">
          <h3 className="text-lg font-display font-semibold text-gray-900">Provide Context for {columnName}</h3>
          <button onClick={onClose} className="p-2 -mr-2 text-gray-400 hover:text-gray-600 rounded-full hover:bg-gray-100 transition-colors">
            <X className="w-5 h-5" />
          </button>
        </div>
        
        <div className="p-6">
          <p className="text-gray-600 text-sm mb-6 leading-relaxed">
            The tool could not determine exactly why values are missing from this column based on the data alone. 
            If you know how this data was collected, you can guide the imputation process.
          </p>

          <div className="space-y-3">
            <label className={`flex items-start gap-3 p-4 rounded-xl border cursor-pointer transition-colors ${
              selected === "mcar" ? "border-blue-500 bg-blue-50/50 ring-1 ring-blue-500" : "border-gray-200 hover:border-gray-300"
            }`}>
              <div className="flex items-center h-5">
                <input type="radio" name="context" value="mcar" checked={selected === "mcar"} onChange={(e) => setSelected(e.target.value)} className="w-4 h-4 text-blue-600 focus:ring-blue-500 border-gray-300" />
              </div>
              <div>
                <div className="text-sm font-medium text-gray-900">Missing completely at random</div>
                <div className="text-xs text-gray-500 mt-1">e.g. A sensor randomly failed, or a page of a survey was accidentally lost.</div>
              </div>
            </label>

            <label className={`flex items-start gap-3 p-4 rounded-xl border cursor-pointer transition-colors ${
              selected === "mnar" ? "border-blue-500 bg-blue-50/50 ring-1 ring-blue-500" : "border-gray-200 hover:border-gray-300"
            }`}>
              <div className="flex items-center h-5">
                <input type="radio" name="context" value="mnar" checked={selected === "mnar"} onChange={(e) => setSelected(e.target.value)} className="w-4 h-4 text-blue-600 focus:ring-blue-500 border-gray-300" />
              </div>
              <div>
                <div className="text-sm font-medium text-gray-900">Missing for a reason tied to the value itself</div>
                <div className="text-xs text-gray-500 mt-1">e.g. People with higher incomes left the income field blank.</div>
              </div>
            </label>

            <label className={`flex items-start gap-3 p-4 rounded-xl border cursor-pointer transition-colors ${
              selected === "not_sure" ? "border-blue-500 bg-blue-50/50 ring-1 ring-blue-500" : "border-gray-200 hover:border-gray-300"
            }`}>
              <div className="flex items-center h-5">
                <input type="radio" name="context" value="not_sure" checked={selected === "not_sure"} onChange={(e) => setSelected(e.target.value)} className="w-4 h-4 text-blue-600 focus:ring-blue-500 border-gray-300" />
              </div>
              <div>
                <div className="text-sm font-medium text-gray-900">Not sure — keep the cautious default</div>
                <div className="text-xs text-gray-500 mt-1">We will proceed using a robust default method.</div>
              </div>
            </label>
          </div>
        </div>

        <div className="px-6 py-4 border-t border-gray-100 flex justify-end gap-3 bg-gray-50/50">
          <button onClick={onClose} className="px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-lg shadow-sm hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500">
            Cancel
          </button>
          <button onClick={() => onApply(selected)} className="px-4 py-2 text-sm font-medium text-white bg-blue-600 border border-transparent rounded-lg shadow-sm hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500">
            Apply and re-run
          </button>
        </div>
      </div>
    </div>
  );
}
